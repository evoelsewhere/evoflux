//! Usage and cost history: every model response this engine makes becomes a
//! row in `evo.db`'s `usage_events` (see `evo_store::usage`).
//!
//! The cost on a response is what the provider computed from the model's
//! models.dev price (`evo_ai::providers::anthropic::cost::calculate_cost`),
//! so the history records what each call cost at the price of its day.
//!
//! The desktop starts each chat's engine with `--session-id`; [`start`] turns
//! recording on for that chat. Without it (tests, other hosts) [`record`] does
//! nothing. Rows go to a writer thread so a model turn never waits on the
//! database; [`flush`] lets the host wait for them before it exits.
//!
//! What records here:
//! - the chat's own agent loop, through [`UsageTap`] around the session's
//!   event emitter (`source = chat`);
//! - subagents (`agent_tool.rs`, `subagent`), plugin child runs
//!   (`child_agents.rs`, `plugin`) and side questions (`side_questions.rs`,
//!   `side`), which call [`record`] from their own observers.
//!
//! Design: `docs/features/usage-and-cost/sdd.md`.

use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use evo_agent::{AgentEmitter, AgentEvent, AgentMessage};
use evo_ai::AssistantMessage;
use evo_store::usage::NewUsage;

/// Which part of the chat made the call.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    Chat,
    Subagent,
    Plugin,
    Side,
}

impl Source {
    pub fn as_str(self) -> &'static str {
        match self {
            Source::Chat => "chat",
            Source::Subagent => "subagent",
            Source::Plugin => "plugin",
            Source::Side => "side",
        }
    }
}

enum Job {
    Row(Box<NewUsage>),
    Flush(Sender<()>),
}

struct Recorder {
    chat_id: Option<String>,
    jobs: Mutex<Sender<Job>>,
}

static RECORDER: OnceLock<Recorder> = OnceLock::new();

/// How many times a batch is tried before it is given up (the database stayed
/// locked past its busy timeout each time).
const ATTEMPTS: u32 = 3;

/// Record this engine's responses for chat `chat_id` from now on. A second
/// call is ignored: one engine serves one chat.
pub fn start(chat_id: Option<String>) {
    start_with(chat_id, |rows| {
        let mut conn = evo_store::open().map_err(|error| error.to_string())?;
        evo_store::usage::record(&mut conn, rows)
            .map(|_| ())
            .map_err(|error| error.to_string())
    });
}

fn start_with<W>(chat_id: Option<String>, write: W)
where
    W: FnMut(&[NewUsage]) -> Result<(), String> + Send + 'static,
{
    if RECORDER.get().is_some() {
        return;
    }
    let (jobs, receiver) = mpsc::channel();
    let recorder = Recorder {
        chat_id,
        jobs: Mutex::new(jobs),
    };
    if RECORDER.set(recorder).is_ok() {
        let spawned = std::thread::Builder::new()
            .name("evo-usage-log".into())
            .spawn(move || writer(receiver, write));
        if let Err(error) = spawned {
            tracing::warn!("usage history is off: could not start its writer: {error}");
        }
    }
}

/// Write rows as they come, a batch at a time. Flush requests are answered
/// once every row queued before them is written (or given up).
fn writer<W>(jobs: Receiver<Job>, mut write: W)
where
    W: FnMut(&[NewUsage]) -> Result<(), String>,
{
    while let Ok(first) = jobs.recv() {
        let mut rows = Vec::new();
        let mut waiting = Vec::new();
        let mut take = |job: Job| match job {
            Job::Row(row) => rows.push(*row),
            Job::Flush(done) => waiting.push(done),
        };
        take(first);
        while let Ok(job) = jobs.try_recv() {
            take(job);
        }
        if !rows.is_empty() {
            let mut attempt = 0;
            loop {
                attempt += 1;
                match write(&rows) {
                    Ok(()) => break,
                    Err(error) if attempt >= ATTEMPTS => {
                        tracing::warn!("usage history: dropped {} responses: {error}", rows.len());
                        break;
                    }
                    Err(_) => std::thread::sleep(Duration::from_millis(250 * u64::from(attempt))),
                }
            }
        }
        for done in waiting {
            let _ = done.send(());
        }
    }
}

/// Record one finished response. Does nothing until [`start`] ran.
pub fn record(message: &AssistantMessage, source: Source) {
    let Some(recorder) = RECORDER.get() else {
        return;
    };
    let row = row_for(recorder.chat_id.clone(), message, source, now_ms());
    if row.is_empty() {
        return;
    }
    let jobs = recorder
        .jobs
        .lock()
        .unwrap_or_else(|error| error.into_inner());
    let _ = jobs.send(Job::Row(Box::new(row)));
}

/// Wait up to `timeout` for every recorded response to reach the database.
pub fn flush(timeout: Duration) {
    let Some(recorder) = RECORDER.get() else {
        return;
    };
    let (done, wait) = mpsc::channel();
    {
        let jobs = recorder
            .jobs
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if jobs.send(Job::Flush(done)).is_err() {
            return;
        }
    }
    match wait.recv_timeout(timeout) {
        Ok(()) | Err(RecvTimeoutError::Disconnected) => {}
        Err(RecvTimeoutError::Timeout) => {
            tracing::warn!("usage history: some responses were not written before exit");
        }
    }
}

fn row_for(
    chat_id: Option<String>,
    message: &AssistantMessage,
    source: Source,
    at_ms: i64,
) -> NewUsage {
    let usage = &message.usage;
    NewUsage {
        at_ms,
        chat_id,
        source: source.as_str().into(),
        provider_id: message.provider.clone(),
        model_id: message.model.clone(),
        input: usage.input,
        output: usage.output,
        cache_read: usage.cache_read,
        cache_write: usage.cache_write,
        reasoning: usage.reasoning.unwrap_or(0),
        cost_input: usage.cost.input,
        cost_output: usage.cost.output,
        cost_cache_read: usage.cost.cache_read,
        cost_cache_write: usage.cost.cache_write,
        cost_usd: usage.cost.total,
        stop_reason: serde_json::to_value(message.stop_reason)
            .ok()
            .and_then(|value| value.as_str().map(str::to_owned)),
        duration_ms: duration(message.timestamp, at_ms),
    }
}

/// Providers stamp a response when its request goes out; it finished at
/// `end`. Anything over an hour (or a missing stamp) is not a duration.
fn duration(started: i64, end: i64) -> Option<i64> {
    let elapsed = end - started;
    (started > 0 && elapsed > 0 && elapsed <= 3_600_000).then_some(elapsed)
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis() as i64)
        .unwrap_or(0)
}

/// The session's emitter with every finished assistant response recorded on
/// the way through. Everything else passes untouched.
pub struct UsageTap {
    inner: Arc<dyn AgentEmitter>,
}

impl UsageTap {
    pub fn new(inner: Arc<dyn AgentEmitter>) -> Self {
        Self { inner }
    }

    fn observe(event: &AgentEvent) {
        if let AgentEvent::MessageEnd {
            message: AgentMessage::Assistant(message),
            ..
        } = event
        {
            record(message, Source::Chat);
        }
    }
}

impl AgentEmitter for UsageTap {
    fn tool_program_observer(
        &self,
    ) -> Option<Arc<dyn evo_agent::tool_program_observation::ToolProgramObserver>> {
        self.inner.tool_program_observer()
    }

    fn emit(&self, event: AgentEvent) -> futures::future::BoxFuture<'static, ()> {
        Self::observe(&event);
        self.inner.emit(event)
    }

    fn emit_injected(&self, event: AgentEvent) -> futures::future::BoxFuture<'static, ()> {
        Self::observe(&event);
        self.inner.emit_injected(event)
    }

    fn try_emit(&self, event: AgentEvent) {
        Self::observe(&event);
        self.inner.try_emit(event)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use evo_ai::{StopReason, Usage, UsageCost};

    fn message(cost: f64) -> AssistantMessage {
        let mut message =
            AssistantMessage::empty(evo_ai::Api::AnthropicMessages, "anthropic", "some-model", 0);
        message.stop_reason = StopReason::Stop;
        message.usage = Usage {
            input: 100,
            output: 20,
            cache_read: 30,
            cache_write: 4,
            cache_write_1h: None,
            reasoning: Some(7),
            total_tokens: 154,
            cost: UsageCost {
                input: cost / 2.0,
                output: cost / 2.0,
                cache_read: 0.0,
                cache_write: 0.0,
                total: cost,
            },
        };
        message
    }

    #[test]
    fn a_row_carries_the_response_usage_and_cost() {
        let row = row_for(Some("chat-1".into()), &message(0.02), Source::Subagent, 42);
        assert_eq!(row.chat_id.as_deref(), Some("chat-1"));
        assert_eq!(row.source, "subagent");
        assert_eq!(
            (row.provider_id.as_str(), row.model_id.as_str()),
            ("anthropic", "some-model")
        );
        assert_eq!(
            (
                row.input,
                row.output,
                row.cache_read,
                row.cache_write,
                row.reasoning
            ),
            (100, 20, 30, 4, 7)
        );
        assert_eq!(row.cost_usd, 0.02);
        assert_eq!(row.stop_reason.as_deref(), Some("stop"));
        assert_eq!(row.at_ms, 42);
        assert_eq!(row.duration_ms, None, "no start stamp, no duration");

        let mut timed = message(0.02);
        timed.timestamp = 10_000;
        assert_eq!(
            row_for(None, &timed, Source::Chat, 12_500).duration_ms,
            Some(2_500)
        );
        assert_eq!(row_for(None, &timed, Source::Chat, 9_000).duration_ms, None);
    }

    #[test]
    fn the_writer_batches_retries_and_answers_flushes() {
        let (jobs, receiver) = mpsc::channel();
        let written = Arc::new(Mutex::new(Vec::<usize>::new()));
        let seen = written.clone();
        let mut failures = 1;
        let thread = std::thread::spawn(move || {
            writer(receiver, move |rows: &[NewUsage]| {
                if failures > 0 {
                    failures -= 1;
                    return Err("database is locked".into());
                }
                seen.lock().unwrap().push(rows.len());
                Ok(())
            })
        });
        let row = row_for(None, &message(0.01), Source::Chat, 1);
        for _ in 0..3 {
            jobs.send(Job::Row(Box::new(row.clone()))).unwrap();
        }
        let (done, wait) = mpsc::channel();
        jobs.send(Job::Flush(done)).unwrap();
        wait.recv_timeout(Duration::from_secs(5)).unwrap();
        let total: usize = written.lock().unwrap().iter().sum();
        assert_eq!(total, 3, "every row is written once, after the retry");
        drop(jobs);
        thread.join().unwrap();
    }
}
