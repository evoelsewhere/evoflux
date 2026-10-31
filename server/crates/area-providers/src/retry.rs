//! Port of `app/agent/agent_loop/retry.py`: retry, backoff, rate-limit and
//! fallback handling around [`Provider::stream`], plus the mapping of provider
//! HTTP errors to typed errors.
//!
//! Python reports progress through agent hooks (`on_rate_limit`,
//! `on_provider_retry`, ...). Here the same notices are items of the returned
//! stream, in the order Python calls the hooks. Dropping the stream is the
//! interrupt.

use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Duration;

use futures_core::future::BoxFuture;
use futures_core::stream::BoxStream;
use futures_util::{FutureExt, StreamExt};
use serde_json::Value;

use crate::{ChatRequest, Provider, ProviderError, ProviderEvent};

/// `MAX_RETRIES`: attempts per provider.
pub const MAX_RETRIES: u32 = 5;

/// `_RETRYABLE_STATUS_CODES`.
const RETRYABLE_STATUS_CODES: [u16; 5] = [429, 500, 502, 503, 504];

/// `_NON_RETRYABLE_429_MARKERS`: quota-style 429s where retrying cannot help.
const NON_RETRYABLE_429_MARKERS: [&str; 11] = [
    "usage_limit_reached",
    "usage_not_included",
    "workspace_owner_credits_depleted",
    "workspace_member_credits_depleted",
    "workspace_owner_usage_limit_reached",
    "workspace_member_usage_limit_reached",
    "quota_exceeded",
    "insufficient_quota",
    "insufficient balance",
    "no resource package",
    "billing_not_active",
];

/// `_BASE_DELAY` (exponential base 3: 1, 3, 9, 27 s) and `_MAX_DELAY`.
const BASE_DELAY: f64 = 1.0;
const MAX_DELAY: f64 = 60.0;

/// `_CONTEXT_OVERFLOW_CODES`.
const CONTEXT_OVERFLOW_CODES: [&str; 2] = ["context_length_exceeded", "context_window_exceeded"];

/// `_CONTEXT_OVERFLOW_PHRASES`.
const CONTEXT_OVERFLOW_PHRASES: [&str; 9] = [
    "context length",
    "context window",
    "context_length",
    "maximum context",
    "prompt is too long",
    "input is too long",
    "too many tokens",
    "exceeds the context",
    "reduce the length",
];

/// One item of [`stream_with_retry`]: a provider event or a retry notice.
#[derive(Debug, Clone, PartialEq)]
pub enum RetryItem {
    Event(ProviderEvent),
    /// `STREAM_RESTART`: a retry began after events were already yielded;
    /// drop what was assembled from them.
    Restart,
    /// `on_rate_limit`.
    RateLimit {
        retry_after: u64,
        attempt: u32,
        max_attempts: u32,
    },
    /// `on_provider_retry`, sent before the backoff sleep.
    Retry {
        model: String,
        attempt: u32,
        max_attempts: u32,
        delay_seconds: f64,
        error_type: String,
        status_code: Option<u16>,
        retry_after: Option<u64>,
    },
    /// `on_provider_exhausted`.
    Exhausted {
        model: String,
        max_attempts: u32,
        error_type: String,
        status_code: Option<u16>,
    },
    /// `on_provider_fallback`.
    Fallback {
        primary: String,
        fallback: String,
    },
}

/// A provider and the label used in logs, notices and error messages.
#[derive(Clone)]
pub struct Target {
    pub provider: Arc<dyn Provider>,
    pub label: String,
}

/// Sleeps for the backoff delay; tests substitute one that records instead.
pub type Sleeper = Arc<dyn Fn(Duration) -> BoxFuture<'static, ()> + Send + Sync>;

/// `stream_with_retry` with real backoff sleeps.
pub fn stream_with_retry(
    primary: Target,
    fallback: Option<Target>,
    req: ChatRequest,
) -> BoxStream<'static, Result<RetryItem, ProviderError>> {
    let sleeper: Sleeper = Arc::new(|delay| tokio::time::sleep(delay).boxed());
    stream_with_retry_using(primary, fallback, req, sleeper)
}

/// `stream_with_retry` with a custom sleeper.
pub fn stream_with_retry_using(
    primary: Target,
    fallback: Option<Target>,
    req: ChatRequest,
    sleeper: Sleeper,
) -> BoxStream<'static, Result<RetryItem, ProviderError>> {
    let mut targets = vec![primary];
    targets.extend(fallback);
    let state = RetryState {
        targets,
        req,
        sleeper,
        target_idx: 0,
        attempt: 0,
        current: None,
        emitted_any: false,
        pending: VecDeque::new(),
        last_error: None,
        finished: false,
    };
    futures_util::stream::unfold(state, |mut state| async move {
        let item = state.next().await?;
        Some((item, state))
    })
    .boxed()
}

enum Step {
    Item(Result<RetryItem, ProviderError>),
    Sleep(f64),
}

struct RetryState {
    targets: Vec<Target>,
    req: ChatRequest,
    sleeper: Sleeper,
    target_idx: usize,
    attempt: u32,
    current: Option<BoxStream<'static, Result<ProviderEvent, ProviderError>>>,
    emitted_any: bool,
    pending: VecDeque<Step>,
    last_error: Option<ProviderError>,
    finished: bool,
}

impl RetryState {
    async fn next(&mut self) -> Option<Result<RetryItem, ProviderError>> {
        loop {
            match self.pending.pop_front() {
                Some(Step::Item(item)) => return Some(item),
                Some(Step::Sleep(seconds)) => {
                    (self.sleeper)(Duration::from_secs_f64(seconds)).await;
                    continue;
                }
                None => {}
            }
            if self.finished {
                return None;
            }
            if let Some(stream) = self.current.as_mut() {
                match stream.next().await {
                    Some(Ok(event)) => {
                        self.emitted_any = true;
                        return Some(Ok(RetryItem::Event(event)));
                    }
                    Some(Err(error)) => {
                        self.current = None;
                        self.on_error(error);
                    }
                    None => {
                        self.current = None;
                        self.finished = true;
                    }
                }
                continue;
            }
            let Some(target) = self.targets.get(self.target_idx).cloned() else {
                self.give_up();
                continue;
            };
            if self.emitted_any {
                self.emitted_any = false;
                return Some(Ok(RetryItem::Restart));
            }
            match target.provider.stream(self.req.clone()).await {
                Ok(stream) => self.current = Some(stream),
                Err(error) => self.on_error(error),
            }
        }
    }

    fn label(&self) -> String {
        self.targets
            .get(self.target_idx)
            .map(|t| t.label.clone())
            .unwrap_or_default()
    }

    fn fail(&mut self, error: ProviderError) {
        self.pending.push_back(Step::Item(Err(error)));
        self.finished = true;
    }

    fn notice(&mut self, item: RetryItem) {
        self.pending.push_back(Step::Item(Ok(item)));
    }

    fn on_error(&mut self, error: ProviderError) {
        let label = self.label();
        let attempt = self.attempt;
        match &error {
            ProviderError::Status { status, body, .. }
                if !RETRYABLE_STATUS_CODES.contains(status) =>
            {
                let logged: String = body.chars().take(500).collect();
                tracing::error!(model = label, status, body = logged, "llm_provider_error");
                let classified = classify_provider_http_error(*status, body, &label);
                self.fail(classified);
            }
            ProviderError::Status {
                status,
                body,
                retry_after: header,
            } => {
                let status = *status;
                let mut retry_after = 0;
                if status == 429 {
                    if is_non_retryable_429(body) {
                        tracing::warn!(
                            model = label,
                            status,
                            attempt = attempt + 1,
                            max = MAX_RETRIES,
                            "llm_provider_non_retryable_rate_limit"
                        );
                        self.last_error = Some(error);
                        self.next_target();
                        return;
                    }
                    retry_after = parse_retry_after(header.as_deref(), body);
                    self.notice(RetryItem::RateLimit {
                        retry_after,
                        attempt: attempt + 1,
                        max_attempts: MAX_RETRIES,
                    });
                }
                self.last_error = Some(error);
                if attempt + 1 >= MAX_RETRIES {
                    tracing::warn!(
                        model = label,
                        status,
                        attempts = MAX_RETRIES,
                        "llm_provider_exhausted"
                    );
                    self.notice(RetryItem::Exhausted {
                        model: label,
                        max_attempts: MAX_RETRIES,
                        error_type: "HTTPStatusError".to_owned(),
                        status_code: Some(status),
                    });
                    self.next_target();
                    return;
                }
                #[allow(clippy::cast_precision_loss)]
                let delay = if retry_after > 0 {
                    (retry_after as f64).min(MAX_DELAY)
                } else {
                    backoff(attempt)
                };
                if status == 429 && delay >= MAX_DELAY {
                    tracing::warn!(
                        model = label,
                        status,
                        attempt = attempt + 1,
                        max = MAX_RETRIES,
                        delay,
                        retry_after,
                        "llm_provider_rate_limit_too_long"
                    );
                    self.next_target();
                    return;
                }
                tracing::warn!(
                    model = label,
                    status,
                    attempt = attempt + 1,
                    max = MAX_RETRIES,
                    delay,
                    retry_after,
                    "llm_provider_retry"
                );
                self.notice(RetryItem::Retry {
                    model: label,
                    attempt: attempt + 1,
                    max_attempts: MAX_RETRIES,
                    delay_seconds: delay,
                    error_type: "HTTPStatusError".to_owned(),
                    status_code: Some(status),
                    retry_after: Some(retry_after),
                });
                self.pending.push_back(Step::Sleep(delay));
                self.attempt += 1;
            }
            ProviderError::Transport {
                error_type,
                transient: true,
                ..
            } => {
                let error_type = error_type.clone();
                self.last_error = Some(error);
                if attempt + 1 >= MAX_RETRIES {
                    tracing::warn!(
                        model = label,
                        error = error_type,
                        attempts = MAX_RETRIES,
                        "llm_provider_exhausted"
                    );
                    self.notice(RetryItem::Exhausted {
                        model: label,
                        max_attempts: MAX_RETRIES,
                        error_type,
                        status_code: None,
                    });
                    self.next_target();
                    return;
                }
                let delay = backoff(attempt);
                tracing::warn!(
                    model = label,
                    error = error_type,
                    attempt = attempt + 1,
                    max = MAX_RETRIES,
                    delay,
                    "llm_provider_retry"
                );
                self.notice(RetryItem::Retry {
                    model: label,
                    attempt: attempt + 1,
                    max_attempts: MAX_RETRIES,
                    delay_seconds: delay,
                    error_type,
                    status_code: None,
                    retry_after: None,
                });
                self.pending.push_back(Step::Sleep(delay));
                self.attempt += 1;
            }
            // Not retryable: raised as is.
            _ => self.fail(error),
        }
    }

    /// The current provider is done retrying: move to the fallback, if any.
    fn next_target(&mut self) {
        let from_primary = self.target_idx == 0;
        self.target_idx += 1;
        self.attempt = 0;
        if let (true, Some(primary), Some(fallback)) =
            (from_primary, self.targets.first(), self.targets.get(1))
        {
            let (primary, fallback) = (primary.label.clone(), fallback.label.clone());
            tracing::warn!(primary, fallback, "llm_provider_fallback");
            self.notice(RetryItem::Fallback { primary, fallback });
        }
    }

    /// Every provider failed: a 429 becomes `ProviderRateLimitError`, anything
    /// else is raised unchanged.
    fn give_up(&mut self) {
        let error = match self.last_error.take() {
            Some(ProviderError::Status { status: 429, .. }) | None => ProviderError::RateLimited,
            Some(other) => other,
        };
        self.fail(error);
    }
}

/// `_BASE_DELAY * 3**attempt`, capped at `_MAX_DELAY`.
fn backoff(attempt: u32) -> f64 {
    (BASE_DELAY * 3f64.powi(i32::try_from(attempt).unwrap_or(i32::MAX))).min(MAX_DELAY)
}

/// `is_non_retryable_429`, for a 429 body.
pub fn is_non_retryable_429(body: &str) -> bool {
    let lowered = body.to_lowercase();
    NON_RETRYABLE_429_MARKERS
        .iter()
        .any(|marker| lowered.contains(marker))
}

fn leading_digits(text: &str) -> &str {
    let end = text
        .find(|c: char| !c.is_ascii_digit())
        .unwrap_or(text.len());
    text.get(..end).unwrap_or_default()
}

fn saturating_u64(digits: &str) -> u64 {
    digits.parse().unwrap_or(u64::MAX)
}

/// `"retryDelay"\s*:\s*"(\d+)s"`, first match.
fn retry_delay_field(body: &str) -> Option<u64> {
    body.match_indices("\"retryDelay\"").find_map(|(at, key)| {
        let rest = body.get(at + key.len()..)?.trim_start();
        let rest = rest.strip_prefix(':')?.trim_start().strip_prefix('"')?;
        let digits = leading_digits(rest);
        let after = rest.get(digits.len()..)?;
        (!digits.is_empty() && after.starts_with("s\"")).then(|| saturating_u64(digits))
    })
}

/// `reset after (\d+)s`, first match.
fn reset_after(body: &str) -> Option<u64> {
    body.match_indices("reset after ").find_map(|(at, key)| {
        let rest = body.get(at + key.len()..)?;
        let digits = leading_digits(rest);
        let after = rest.get(digits.len()..)?;
        (!digits.is_empty() && after.starts_with('s')).then(|| saturating_u64(digits))
    })
}

/// `try again in\s+(\d+(?:\.\d+)?)\s*(ms|s|seconds?)` (case-insensitive), first match.
fn try_again_in(body: &str) -> Option<u64> {
    let lowered = body.to_ascii_lowercase();
    lowered.match_indices("try again in").find_map(|(at, key)| {
        let rest = lowered.get(at + key.len()..)?;
        let number_start = rest.trim_start();
        if number_start.len() == rest.len() {
            return None;
        }
        let whole = leading_digits(number_start);
        if whole.is_empty() {
            return None;
        }
        let mut number_len = whole.len();
        if let Some(fraction) = number_start.get(whole.len()..)?.strip_prefix('.') {
            let digits = leading_digits(fraction);
            if !digits.is_empty() {
                number_len += 1 + digits.len();
            }
        }
        let value: f64 = number_start.get(..number_len)?.parse().ok()?;
        let unit = number_start.get(number_len..)?.trim_start();
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
        if unit.starts_with("ms") {
            Some(((value / 1000.0) as u64).max(1))
        } else if unit.starts_with('s') {
            Some((value as u64).max(1))
        } else {
            None
        }
    })
}

/// `parse_retry_after`: the `Retry-After` header when it is all digits, then
/// Google's `retryDelay`, then "reset after Ns", then "try again in N(s|ms)";
/// 0 when none applies.
pub fn parse_retry_after(header: Option<&str>, body: &str) -> u64 {
    if let Some(header) = header.filter(|h| !h.is_empty() && h.chars().all(|c| c.is_ascii_digit()))
    {
        return saturating_u64(header);
    }
    retry_delay_field(body)
        .or_else(|| reset_after(body))
        .or_else(|| try_again_in(body))
        .unwrap_or(0)
}

fn non_blank(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
}

/// `_extract_provider_error_message`.
pub fn extract_provider_error_message(body: &str) -> Option<String> {
    let data: Value = serde_json::from_str(body).ok()?;
    let data = data.as_object()?;
    match data.get("error") {
        Some(Value::Object(error)) => {
            if let Some(message) = non_blank(error.get("message")) {
                return Some(message);
            }
        }
        error @ Some(Value::String(_)) => {
            if let Some(message) = non_blank(error) {
                return Some(message);
            }
        }
        _ => {}
    }
    non_blank(data.get("message")).or_else(|| non_blank(data.get("detail")))
}

/// `is_context_overflow_response`.
pub fn is_context_overflow_response(status: u16, body: &str) -> bool {
    if status == 413 {
        return true;
    }
    if status != 400 {
        return false;
    }
    let data: Option<Value> = serde_json::from_str(body).ok();
    if let Some(Value::Object(error)) = data.as_ref().and_then(|d| d.get("error")) {
        for key in ["code", "type"] {
            if let Some(value) = error.get(key).and_then(Value::as_str) {
                if CONTEXT_OVERFLOW_CODES.contains(&value.to_lowercase().as_str()) {
                    return true;
                }
            }
        }
    }
    let lowered = body.to_lowercase();
    CONTEXT_OVERFLOW_CODES
        .iter()
        .chain(CONTEXT_OVERFLOW_PHRASES.iter())
        .any(|needle| lowered.contains(needle))
}

/// `classify_provider_http_error`: a non-retryable provider HTTP error as the
/// typed error the UI renders.
pub fn classify_provider_http_error(
    status: u16,
    body: &str,
    provider_label: &str,
) -> ProviderError {
    let detail = if body.is_empty() {
        None
    } else {
        extract_provider_error_message(body)
    };
    let suffix = detail
        .as_ref()
        .map(|d| format!(": {d}"))
        .unwrap_or_default();
    let punctuation = match &detail {
        Some(d) if d.ends_with(['.', '!', '?']) => "",
        _ => ".",
    };
    let provider = provider_label.to_owned();
    if status == 401 || status == 403 {
        return ProviderError::Authentication {
            message: format!(
                "{provider_label} rejected the request — authentication failed \
                 (HTTP {status}){suffix}{punctuation} Check the provider's API key \
                 / login in Settings → Providers."
            ),
            status_code: status,
            provider,
        };
    }
    if is_context_overflow_response(status, body) {
        return ProviderError::ContextOverflow {
            message: format!(
                "{provider_label} rejected the request — the conversation is \
                 longer than the model's context window (HTTP {status}){suffix}{punctuation}"
            ),
            status_code: status,
            provider,
        };
    }
    ProviderError::Request {
        message: format!(
            "{provider_label} rejected the request (HTTP {status}){suffix}{punctuation}"
        ),
        status_code: status,
        provider,
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::type_complexity
)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    #[test]
    fn retry_after_sources_in_order() {
        assert_eq!(parse_retry_after(Some("7"), "reset after 3s"), 7);
        assert_eq!(parse_retry_after(Some("1.5"), "reset after 3s"), 3);
        assert_eq!(parse_retry_after(Some(""), ""), 0);
        let google =
            r#"{"error":{"details":[{"retryDelay": "x"},{"metadata":{"retryDelay" :  "33s"}}]}}"#;
        assert_eq!(parse_retry_after(None, google), 33);
        assert_eq!(parse_retry_after(None, r#""retryDelay":"5ms""#), 0);
        assert_eq!(
            parse_retry_after(None, "reset after xs, reset after 12s"),
            12
        );
        assert_eq!(parse_retry_after(None, "Reset After 12s"), 0);
        assert_eq!(parse_retry_after(None, "reset after s"), 0);
        assert_eq!(parse_retry_after(None, "reset after 5m"), 0);
        assert_eq!(parse_retry_after(None, r#""retryDelay": "s""#), 0);
        assert_eq!(parse_retry_after(None, "Please TRY AGAIN IN 11.054s"), 11);
        assert_eq!(parse_retry_after(None, "try again in 35 seconds"), 35);
        assert_eq!(parse_retry_after(None, "try again in 0.2s"), 1);
        assert_eq!(parse_retry_after(None, "try again in 2500ms"), 2);
        assert_eq!(parse_retry_after(None, "try again in 300 MS"), 1);
        assert_eq!(parse_retry_after(None, "try again in5s"), 0);
        assert_eq!(
            parse_retry_after(None, "try again in soon, try again in 4 s"),
            4
        );
        assert_eq!(parse_retry_after(None, "try again in 1.x s"), 0);
        assert_eq!(parse_retry_after(None, "try again in 3m"), 0);
        assert_eq!(parse_retry_after(None, "nothing"), 0);
    }

    #[test]
    fn quota_markers_are_case_insensitive() {
        assert!(is_non_retryable_429("{\"code\":\"INSUFFICIENT_QUOTA\"}"));
        assert!(is_non_retryable_429("No Resource Package left"));
        assert!(!is_non_retryable_429("slow down"));
    }

    #[test]
    fn error_messages_from_every_body_shape() {
        let m = |b: &str| extract_provider_error_message(b);
        assert_eq!(
            m(r#"{"error":{"message":" bad "}}"#).as_deref(),
            Some("bad")
        );
        assert_eq!(
            m(r#"{"error":{"message":"  "},"message":"top"}"#).as_deref(),
            Some("top")
        );
        assert_eq!(m(r#"{"error":"plain"}"#).as_deref(), Some("plain"));
        assert_eq!(m(r#"{"error":" ","detail":"d"}"#).as_deref(), Some("d"));
        assert_eq!(m(r#"{"message":5,"detail":"d"}"#).as_deref(), Some("d"));
        assert_eq!(m(r#"["x"]"#), None);
        assert_eq!(m("not json"), None);
        assert_eq!(m(r#"{"error":{}}"#), None);
    }

    #[test]
    fn context_overflow_detection() {
        assert!(is_context_overflow_response(413, ""));
        assert!(!is_context_overflow_response(422, "context length"));
        assert!(is_context_overflow_response(
            400,
            r#"{"error":{"type":"Context_Window_Exceeded"}}"#
        ));
        assert!(is_context_overflow_response(400, "Prompt is too long"));
        assert!(!is_context_overflow_response(
            400,
            r#"{"error":{"code":"max_tokens"}}"#
        ));
    }

    #[test]
    fn classification_and_punctuation() {
        let e = classify_provider_http_error(401, r#"{"error":{"message":"Nope!"}}"#, "p:m");
        assert_eq!(
            e.to_string(),
            "p:m rejected the request — authentication failed (HTTP 401): Nope! \
             Check the provider's API key / login in Settings → Providers."
        );
        let e = classify_provider_http_error(404, "", "p:m");
        assert_eq!(e.to_string(), "p:m rejected the request (HTTP 404).");
        assert_eq!(e.status_code(), Some(404));
        let e = classify_provider_http_error(400, r#"{"error":{"message":"Why?"}}"#, "p:m");
        assert_eq!(e.to_string(), "p:m rejected the request (HTTP 400): Why?");
        assert!(matches!(
            classify_provider_http_error(413, "", "p"),
            ProviderError::ContextOverflow {
                status_code: 413,
                ..
            }
        ));
    }

    #[test]
    fn backoff_is_capped() {
        let delays: Vec<f64> = (0..6).map(backoff).collect();
        assert_eq!(delays, vec![1.0, 3.0, 9.0, 27.0, 60.0, 60.0]);
    }

    /// A provider that replays a script of outcomes, one per call.
    struct Scripted {
        calls: Mutex<VecDeque<Vec<Result<ProviderEvent, ProviderError>>>>,
        start_errors: Mutex<VecDeque<Option<ProviderError>>>,
    }

    impl Scripted {
        fn new(
            script: Vec<(
                Option<ProviderError>,
                Vec<Result<ProviderEvent, ProviderError>>,
            )>,
        ) -> Arc<Self> {
            let (starts, calls) = script.into_iter().unzip();
            Arc::new(Self {
                calls: Mutex::new(calls),
                start_errors: Mutex::new(starts),
            })
        }
    }

    #[async_trait::async_trait]
    impl Provider for Scripted {
        async fn stream(
            &self,
            _req: ChatRequest,
        ) -> Result<BoxStream<'static, Result<ProviderEvent, ProviderError>>, ProviderError>
        {
            let start = self.start_errors.lock().unwrap().pop_front().flatten();
            let events = self.calls.lock().unwrap().pop_front().unwrap_or_default();
            match start {
                Some(error) => Err(error),
                None => Ok(futures_util::stream::iter(events).boxed()),
            }
        }
    }

    fn status(code: u16, body: &str) -> ProviderError {
        ProviderError::Status {
            status: code,
            body: body.to_owned(),
            retry_after: None,
        }
    }

    fn reset() -> ProviderError {
        ProviderError::Transport {
            error_type: "ReadError".into(),
            message: "reset".into(),
            transient: true,
        }
    }

    fn text(t: &str) -> Result<ProviderEvent, ProviderError> {
        Ok(ProviderEvent::TextDelta(t.into()))
    }

    fn request() -> ChatRequest {
        ChatRequest {
            model: String::new(),
            messages: vec![],
            tools: vec![],
            options: Value::Null,
        }
    }

    async fn run(
        primary: Arc<Scripted>,
        fallback: Option<Arc<Scripted>>,
    ) -> (Vec<Result<RetryItem, ProviderError>>, Vec<Duration>) {
        let slept = Arc::new(Mutex::new(Vec::new()));
        let record = slept.clone();
        let sleeper: Sleeper = Arc::new(move |d| {
            record.lock().unwrap().push(d);
            async {}.boxed()
        });
        let target = |p: Arc<Scripted>, label: &str| Target {
            provider: p,
            label: label.into(),
        };
        let items = stream_with_retry_using(
            target(primary, "primary"),
            fallback.map(|f| target(f, "fallback")),
            request(),
            sleeper,
        )
        .collect()
        .await;
        let slept = slept.lock().unwrap().clone();
        (items, slept)
    }

    #[tokio::test]
    async fn a_mid_stream_failure_restarts_the_stream() {
        let primary = Scripted::new(vec![
            (None, vec![text("par"), Err(reset())]),
            (None, vec![text("full")]),
        ]);
        let (items, slept) = run(primary, None).await;
        let kinds: Vec<String> = items
            .iter()
            .map(|i| format!("{:?}", i.as_ref().unwrap()))
            .collect();
        assert_eq!(kinds.len(), 4, "{kinds:?}");
        assert_eq!(
            items[0],
            Ok(RetryItem::Event(ProviderEvent::TextDelta("par".into())))
        );
        assert!(
            matches!(&items[1], Ok(RetryItem::Retry { error_type, status_code: None, retry_after: None, .. }) if error_type == "ReadError")
        );
        assert_eq!(items[2], Ok(RetryItem::Restart));
        assert_eq!(
            items[3],
            Ok(RetryItem::Event(ProviderEvent::TextDelta("full".into())))
        );
        assert_eq!(slept, vec![Duration::from_secs(1)]);
    }

    #[tokio::test]
    async fn fallback_runs_after_the_primary_gives_up() {
        let primary = Scripted::new(vec![(Some(status(429, "insufficient_quota")), vec![])]);
        let fallback = Scripted::new(vec![(None, vec![text("ok")])]);
        let (items, _) = run(primary, Some(fallback)).await;
        assert_eq!(
            items,
            vec![
                Ok(RetryItem::Fallback {
                    primary: "primary".into(),
                    fallback: "fallback".into()
                }),
                Ok(RetryItem::Event(ProviderEvent::TextDelta("ok".into()))),
            ]
        );
    }

    #[tokio::test]
    async fn fallback_after_events_restarts_and_last_error_wins() {
        let script = || {
            let mut s = vec![(None, vec![text("a"), Err(status(502, ""))])];
            s.extend((0..4).map(|_| (Some(status(502, "")), vec![])));
            s
        };
        let primary = Scripted::new(script());
        let fallback = Scripted::new(vec![(None, vec![text("b"), Err(reset())]); 5]);
        let (items, slept) = run(primary, Some(fallback)).await;
        let restart_at = items
            .iter()
            .position(|i| *i == Ok(RetryItem::Restart))
            .unwrap();
        let fallback_at = items
            .iter()
            .position(|i| matches!(i, Ok(RetryItem::Fallback { .. })))
            .unwrap();
        assert!(restart_at < fallback_at);
        assert_eq!(
            items
                .iter()
                .filter(|i| **i == Ok(RetryItem::Restart))
                .count(),
            5
        );
        assert!(
            matches!(items.last(), Some(Err(ProviderError::Transport { error_type, .. })) if error_type == "ReadError")
        );
        assert_eq!(slept.len(), 8);
    }

    #[tokio::test]
    async fn non_retryable_errors_end_the_stream_at_once() {
        let primary = Scripted::new(vec![(
            None,
            vec![Err(ProviderError::InvalidChunk("x".into()))],
        )]);
        let (items, slept) = run(primary, None).await;
        assert_eq!(items, vec![Err(ProviderError::InvalidChunk("x".into()))]);
        assert!(slept.is_empty());
        let config = Scripted::new(vec![(Some(ProviderError::Config("no key".into())), vec![])]);
        let (items, _) = run(config, None).await;
        assert_eq!(items, vec![Err(ProviderError::Config("no key".into()))]);
        let refused = ProviderError::Transport {
            error_type: "UnsupportedProtocol".into(),
            message: "x".into(),
            transient: false,
        };
        let bad = Scripted::new(vec![(Some(refused.clone()), vec![])]);
        let (items, _) = run(bad, None).await;
        assert_eq!(items, vec![Err(refused)]);
    }

    #[tokio::test]
    async fn real_sleeper_waits_for_the_backoff() {
        tokio::time::pause();
        let primary = Scripted::new(vec![
            (Some(status(503, "")), vec![]),
            (None, vec![text("x")]),
        ]);
        let start = tokio::time::Instant::now();
        let items: Vec<_> = stream_with_retry(
            Target {
                provider: primary,
                label: "p".into(),
            },
            None,
            request(),
        )
        .collect()
        .await;
        assert_eq!(items.len(), 2);
        assert!(start.elapsed() >= Duration::from_secs(1));
    }
}
