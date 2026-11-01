//! Port of app/services/memory_stream_store.py: the in-memory turn journal
//! behind `GET /api/team/{session_id}/stream`.
//!
//! Each session has one turn state: its replayable wire frames in producer
//! order and the live subscribers. Attaching takes the journal and registers
//! the subscriber in one critical section, so no frame is lost or repeated.
//! `done` ends every subscriber; state expires `STREAM_TTL` after the last write.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use serde_json::Value;
use tokio::sync::mpsc;

use crate::pyjson;

/// `STREAM_TTL`.
const STREAM_TTL: Duration = Duration::from_secs(3600);
/// The subscriber queue size (`asyncio.Queue(maxsize=2048)`).
const QUEUE_SIZE: usize = 2048;

/// `_NON_REPLAYABLE_EVENT_TYPES` (plus `done`, never journaled).
const NON_REPLAYABLE: [&str; 7] = [
    "inbox",
    "delegation",
    "handoff",
    "summarization_content",
    "desktop_notification",
    "next_message_suggestion",
    "done",
];

/// `_AGENT_CONTENT_EVENT_TYPES`: dropped from replay once the agent's message is durable.
const AGENT_CONTENT: [&str; 11] = [
    "message",
    "thinking",
    "tool_call",
    "tool_start",
    "tool_output_delta",
    "tool_end",
    "widget_delta",
    "ui_block",
    "visual_artifact",
    "motion_progress",
    "provider_status",
];

/// One SSE frame: the `event:` name and the `data:` JSON text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Frame {
    pub event: String,
    pub data: String,
}

#[derive(Debug, Clone)]
struct Journaled {
    frame: Frame,
    agent: String,
}

#[derive(Default)]
struct TurnState {
    streaming: bool,
    journal: Vec<Journaled>,
    subscribers: Vec<mpsc::Sender<Frame>>,
    /// Bumped on every write, so an expiry timer only removes untouched state.
    generation: u64,
}

#[derive(Default)]
pub(crate) struct StreamStore {
    turns: Mutex<HashMap<String, TurnState>>,
}

impl StreamStore {
    fn turns(&self) -> MutexGuard<'_, HashMap<String, TurnState>> {
        self.turns
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
    }

    /// `init_turn`: a fresh state for a new turn. With `keep_subscribers` an
    /// existing state is reset in place and its subscribers stay attached;
    /// otherwise they are ended.
    pub(crate) fn init_turn(self: &Arc<Self>, session_id: &str, keep_subscribers: bool) {
        let mut turns = self.turns();
        let state = turns.entry(session_id.to_owned()).or_default();
        if !keep_subscribers {
            state.subscribers.clear();
        }
        state.streaming = true;
        state.journal.clear();
        state.generation += 1;
        let generation = state.generation;
        drop(turns);
        self.schedule_expiry(session_id, generation);
    }

    /// `push_event`: journal (when replayable) and fan out one event.
    pub(crate) fn push(self: &Arc<Self>, session_id: &str, event: &str, data: &Value) {
        let frame = Frame {
            event: event.to_owned(),
            data: pyjson::dumps(data),
        };
        let agent = data
            .get("agent")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let mut turns = self.turns();
        let Some(state) = turns.get_mut(session_id) else {
            return;
        };
        if event == "done" {
            state.streaming = false;
        }
        if !NON_REPLAYABLE.contains(&event) {
            state.journal.push(Journaled {
                frame: frame.clone(),
                agent,
            });
        }
        // A full queue is a stalled client: drop it so its stream ends and the
        // client reloads from the database, as Python does with its sentinel.
        state
            .subscribers
            .retain(|tx| tx.try_send(frame.clone()).is_ok());
        state.generation += 1;
        let generation = state.generation;
        drop(turns);
        self.schedule_expiry(session_id, generation);
    }

    /// `commit_agent_content`: once the agent's message is in the database a
    /// reconnect must not replay it.
    pub(crate) fn commit_agent_content(&self, session_id: &str, agent: &str) {
        if let Some(state) = self.turns().get_mut(session_id) {
            state
                .journal
                .retain(|j| !(j.agent == agent && AGENT_CONTENT.contains(&j.frame.event.as_str())));
        }
    }

    /// `mark_done`: end the turn and every attached stream.
    pub(crate) fn mark_done(&self, session_id: &str) {
        if let Some(state) = self.turns().get_mut(session_id) {
            state.streaming = false;
            state.subscribers.clear();
        }
    }

    /// `running_session_ids` for one session.
    pub(crate) fn is_running(&self, session_id: &str) -> bool {
        self.turns()
            .get(session_id)
            .is_some_and(|state| state.streaming)
    }

    /// `attach`: the replay journal and a live receiver, or `None` when the
    /// session has no turn in flight.
    pub(crate) fn attach(&self, session_id: &str) -> Option<(Vec<Frame>, mpsc::Receiver<Frame>)> {
        let mut turns = self.turns();
        let state = turns.get_mut(session_id)?;
        if !state.streaming {
            return None;
        }
        let (tx, rx) = mpsc::channel(QUEUE_SIZE);
        state.subscribers.push(tx);
        let replay = state.journal.iter().map(|j| j.frame.clone()).collect();
        Some((replay, rx))
    }

    fn schedule_expiry(self: &Arc<Self>, session_id: &str, generation: u64) {
        let Ok(handle) = tokio::runtime::Handle::try_current() else {
            return;
        };
        let store = Arc::downgrade(self);
        let session_id = session_id.to_owned();
        handle.spawn(async move {
            tokio::time::sleep(STREAM_TTL).await;
            if let Some(store) = store.upgrade() {
                let mut turns = store.turns();
                if turns.get(&session_id).map(|s| s.generation) == Some(generation) {
                    turns.remove(&session_id);
                }
            }
        });
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    use serde_json::json;

    fn names(frames: &[Frame]) -> Vec<&str> {
        frames.iter().map(|f| f.event.as_str()).collect()
    }

    #[tokio::test]
    async fn attach_without_a_turn_is_none() {
        let store = Arc::new(StreamStore::default());
        assert!(store.attach("s").is_none());
        store.push("s", "message", &json!({"agent": "a"}));
        assert!(store.attach("s").is_none());
        assert!(!store.is_running("s"));
    }

    #[tokio::test]
    async fn replay_then_live_then_done() {
        let store = Arc::new(StreamStore::default());
        store.init_turn("s", false);
        assert!(store.is_running("s"));
        store.push(
            "s",
            "agent_status",
            &json!({"type": "agent_status", "agent": "a"}),
        );
        store.push("s", "desktop_notification", &json!({}));
        let (replay, mut rx) = store.attach("s").unwrap();
        assert_eq!(names(&replay), ["agent_status"]);
        assert_eq!(replay[0].data, r#"{"type": "agent_status", "agent": "a"}"#);
        store.push("s", "message", &json!({"agent": "a", "text": "hi"}));
        store.push("s", "done", &json!({"type": "done"}));
        assert!(!store.is_running("s"));
        store.mark_done("s");
        assert_eq!(rx.recv().await.unwrap().event, "message");
        assert_eq!(rx.recv().await.unwrap().event, "done");
        assert!(rx.recv().await.is_none());
        assert!(store.attach("s").is_none());
    }

    #[tokio::test]
    async fn committed_agent_content_leaves_replay() {
        let store = Arc::new(StreamStore::default());
        store.init_turn("s", false);
        for event in ["agent_status", "message", "tool_call", "usage"] {
            store.push("s", event, &json!({"agent": "a"}));
        }
        store.push("s", "message", &json!({"agent": "b"}));
        store.commit_agent_content("s", "a");
        let (replay, _rx) = store.attach("s").unwrap();
        assert_eq!(names(&replay), ["agent_status", "usage", "message"]);
    }

    #[tokio::test]
    async fn init_turn_resets_journal_and_optionally_keeps_subscribers() {
        let store = Arc::new(StreamStore::default());
        store.init_turn("s", false);
        store.push("s", "agent_status", &json!({}));
        let (_, mut kept) = store.attach("s").unwrap();
        store.init_turn("s", true);
        let (replay, _rx) = store.attach("s").unwrap();
        assert!(replay.is_empty());
        store.push("s", "message", &json!({}));
        assert_eq!(kept.recv().await.unwrap().event, "message");
        store.init_turn("s", false);
        assert!(kept.recv().await.is_none());
    }

    #[tokio::test]
    async fn a_full_subscriber_is_dropped() {
        let store = Arc::new(StreamStore::default());
        store.init_turn("s", false);
        let (_, mut rx) = store.attach("s").unwrap();
        for _ in 0..=QUEUE_SIZE {
            store.push("s", "usage", &json!({}));
        }
        let mut received = 0;
        while rx.recv().await.is_some() {
            received += 1;
        }
        assert_eq!(received, QUEUE_SIZE);
    }

    #[tokio::test(start_paused = true)]
    async fn state_expires_after_the_ttl() {
        let store = Arc::new(StreamStore::default());
        store.init_turn("s", false);
        tokio::time::sleep(STREAM_TTL - Duration::from_secs(1)).await;
        store.push("s", "usage", &json!({}));
        tokio::time::sleep(Duration::from_secs(2)).await;
        assert!(store.is_running("s"));
        tokio::time::sleep(STREAM_TTL).await;
        assert!(!store.is_running("s"));

        // A second turn restarts the clock, so the first timer leaves it alone.
        store.init_turn("t", false);
        tokio::time::sleep(STREAM_TTL / 2).await;
        store.init_turn("t", false);
        tokio::time::sleep(STREAM_TTL / 2 + Duration::from_secs(1)).await;
        assert!(store.is_running("t"));
    }
}
