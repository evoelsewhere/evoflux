//! Port of `CompletionsHandler.stream` (`app/agent/providers/openai/completions.py`)
//! with the headers of `OpenAIProvider._build_headers`.

use std::time::Duration;

use futures_core::stream::BoxStream;
use futures_util::StreamExt;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue, AUTHORIZATION, CONTENT_TYPE};
use serde_json::{Map, Value};

use crate::factory::Resolved;
use crate::request::{build_request, BuildRequest};
use crate::stream::EventDecoder;
use crate::{ChatRequest, Provider, ProviderError, ProviderEvent};

/// `timeout=120.0` on the `httpx` stream: connect and per-read.
pub const STREAM_TIMEOUT: Duration = Duration::from_secs(120);

/// How much of an error body is logged (`err_body[:500]`).
const LOGGED_BODY_CHARS: usize = 500;

/// An OpenAI-compatible Chat Completions provider (`ChatCompletionsOnlyProvider`,
/// `Router9Provider`, `XiaomiProvider`).
pub struct CompatibleProvider {
    client: evoflux_net::Client,
    resolved: Resolved,
}

impl CompatibleProvider {
    pub fn new(client: evoflux_net::Client, resolved: Resolved) -> Self {
        Self { client, resolved }
    }

    /// The wire model: the request's model without this provider's `id:`
    /// prefix, or the model `provider_for` resolved when the request names none.
    fn wire_model<'a>(&'a self, requested: &'a str) -> &'a str {
        if requested.is_empty() {
            return &self.resolved.model;
        }
        requested
            .strip_prefix(self.resolved.config.id)
            .and_then(|rest| rest.strip_prefix(':'))
            .unwrap_or(requested)
    }

    fn headers(&self) -> Result<HeaderMap, ProviderError> {
        let mut headers = HeaderMap::new();
        let mut auth = HeaderValue::from_str(&format!("Bearer {}", self.resolved.api_key))
            .map_err(|_| {
                ProviderError::Config("API key contains characters a header cannot carry.".into())
            })?;
        auth.set_sensitive(true);
        headers.insert(AUTHORIZATION, auth);
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        for (name, value) in self.resolved.config.headers {
            headers.insert(
                HeaderName::from_static(name),
                HeaderValue::from_static(value),
            );
        }
        Ok(headers)
    }
}

/// Map a `reqwest` error to the `httpx` exception Python would see, and
/// whether `TRANSIENT_TRANSPORT_ERRORS` retries it.
pub(crate) fn transport_error(error: &reqwest::Error, reading_body: bool) -> ProviderError {
    let (error_type, transient) = if error.is_timeout() {
        (
            if error.is_connect() {
                "ConnectTimeout"
            } else {
                "ReadTimeout"
            },
            true,
        )
    } else if error.is_connect() {
        ("ConnectError", true)
    } else if reading_body || error.is_body() || error.is_decode() {
        ("ReadError", true)
    } else if error.is_request() {
        ("RemoteProtocolError", true)
    } else {
        ("UnsupportedProtocol", false)
    };
    ProviderError::Transport {
        error_type: error_type.to_owned(),
        message: error.to_string(),
        transient,
    }
}

fn options(value: &Value) -> Result<Map<String, Value>, ProviderError> {
    match value {
        Value::Null => Ok(Map::new()),
        Value::Object(map) => Ok(map.clone()),
        _ => Err(ProviderError::InvalidOption {
            name: "options".to_owned(),
            reason: "expected an object".to_owned(),
        }),
    }
}

#[async_trait::async_trait]
impl Provider for CompatibleProvider {
    async fn stream(
        &self,
        req: ChatRequest,
    ) -> Result<BoxStream<'static, Result<ProviderEvent, ProviderError>>, ProviderError> {
        let options = options(&req.options)?;
        let model = self.wire_model(&req.model);
        let body = build_request(&BuildRequest {
            provider_id: self.resolved.config.id,
            model,
            flavor: self.resolved.config.flavor,
            messages: &req.messages,
            tools: &req.tools,
            options: &options,
        })?;
        let url = format!("{}/chat/completions", self.resolved.base_url);
        let response = self
            .client
            .post(url)
            .headers(self.headers()?)
            .json(&body)
            .send()
            .await
            .map_err(|e| transport_error(&e, false))?;
        let status = response.status().as_u16();
        if status >= 400 {
            let retry_after = response
                .headers()
                .get("retry-after")
                .and_then(|v| v.to_str().ok())
                .map(str::to_owned);
            let body = response
                .text()
                .await
                .map_err(|e| transport_error(&e, true))?;
            let logged: String = body.chars().take(LOGGED_BODY_CHARS).collect();
            tracing::error!(status, body = logged, "openai_stream_error");
            return Err(ProviderError::Status {
                status,
                body,
                retry_after,
            });
        }
        let body = response
            .bytes_stream()
            .map(|chunk| chunk.map_err(|e| transport_error(&e, true)));
        Ok(events(body))
    }
}

/// Decode a response body into provider events. A body error ends the
/// stream with that error and no `Done`, as the exception does in Python.
pub(crate) fn events<S, B>(body: S) -> BoxStream<'static, Result<ProviderEvent, ProviderError>>
where
    S: futures_core::Stream<Item = Result<B, ProviderError>> + Send + 'static,
    B: AsRef<[u8]>,
{
    struct State<S> {
        body: std::pin::Pin<Box<S>>,
        decoder: EventDecoder,
        finished: bool,
    }
    let state = State {
        body: Box::pin(body),
        decoder: EventDecoder::default(),
        finished: false,
    };
    futures_util::stream::unfold(state, |mut state| async move {
        loop {
            if let Some(item) = state.decoder.pop() {
                return Some((item, state));
            }
            if state.finished {
                return None;
            }
            let next = if state.decoder.is_done() {
                None
            } else {
                state.body.next().await
            };
            match next {
                Some(Ok(bytes)) => state.decoder.push(bytes.as_ref()),
                Some(Err(error)) => {
                    state.finished = true;
                    state.decoder.fail(error);
                }
                None => {
                    state.finished = true;
                    state.decoder.finish();
                }
            }
        }
    })
    .boxed()
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::indexing_slicing)]
mod tests;
