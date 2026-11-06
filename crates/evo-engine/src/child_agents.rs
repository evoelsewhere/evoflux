//! Bounded, plugin-owned child runs. Execution bindings stay inside the host.
//!
//! `start` with `"isolation": "worktree"` runs the child in a managed Git
//! worktree of the project (see `crate::worktrees`): its file and shell tools
//! work there, and when it finishes an unchanged worktree is removed while a
//! changed one is kept and reported (`result.worktree`).
use std::collections::{HashMap, HashSet, VecDeque};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use evo_agent::{AgentEmitter, AgentEvent};
use evo_ai::types::AssistantMessageEvent;
use evo_harness::agent_harness::{AgentHarness, ChildHarness};
use evo_harness::session::memory::{InMemorySessionStorage, SystemClock};
use evo_harness::session::session::DefaultIdGenerator;
use evo_harness::session::types::SessionMetadata;
use evo_harness::session::Session;
use futures::FutureExt;
use serde_json::{json, Value};
use tokio_util::sync::CancellationToken;

const MAX_JOBS: usize = 16;
const MAX_OUTPUT: usize = 4 * 1024 * 1024;
const MAX_EVENTS: usize = 8192;

#[derive(Default)]
pub(crate) struct ChildAgents {
    jobs: Mutex<HashMap<String, Arc<Job>>>,
    revoked: Mutex<HashSet<u64>>,
    active: Arc<AtomicUsize>,
}

struct Permit(Arc<AtomicUsize>);
impl Drop for Permit {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}

struct Job {
    owner: u64,
    /// Its mesh node (`s_<session>/a_<child>`).
    address: crate::mesh::Address,
    cancel: CancellationToken,
    invocation_signal: Option<CancellationToken>,
    state: Mutex<State>,
}

#[derive(Default)]
struct State {
    deltas: VecDeque<String>,
    bytes: usize,
    events: usize,
    turns: u32,
    result: Option<Value>,
    error: Option<String>,
    usage: crate::mesh::MeshUsage,
}

impl Job {
    fn fail(&self, error: impl Into<String>) {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        if state.result.is_none() && state.error.is_none() {
            state.error = Some(error.into());
        }
        self.cancel.cancel();
    }

    fn observe(&self, event: AgentEvent) {
        let router = crate::mesh::router();
        router.event(&self.address, &event);
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        if state.result.is_some() || state.error.is_some() {
            return;
        }
        match event {
            AgentEvent::TurnEnd { .. } => {
                state.turns += 1;
                let turns = state.turns;
                drop(state);
                router.activity(&self.address, turns, 0, None, None);
            }
            AgentEvent::MessageEnd {
                message: evo_agent::AgentMessage::Assistant(message),
                ..
            } => {
                state.usage.add(&crate::mesh::usage_of(&message.usage));
                let usage = state.usage;
                drop(state);
                router.usage(&self.address, usage);
            }
            AgentEvent::MessageUpdate {
                assistant_message_event: AssistantMessageEvent::TextDelta { delta, .. },
                ..
            } => {
                if state.bytes.saturating_add(delta.len()) > MAX_OUTPUT
                    || state.events >= MAX_EVENTS
                {
                    state.error = Some("child output limit exceeded".into());
                    self.cancel.cancel();
                } else {
                    state.bytes += delta.len();
                    state.events += 1;
                    state.deltas.push_back(delta);
                }
            }
            _ => {}
        }
    }
}

struct Emitter(Arc<Job>);
impl AgentEmitter for Emitter {
    fn emit(&self, event: AgentEvent) -> futures::future::BoxFuture<'static, ()> {
        self.0.observe(event);
        Box::pin(async {})
    }
    fn try_emit(&self, event: AgentEvent) {
        self.0.observe(event);
    }
}

impl Drop for ChildAgents {
    fn drop(&mut self) {
        self.cancel_all();
    }
}

impl ChildAgents {
    pub(crate) fn cancel_owner(&self, owner: u64) {
        self.revoked
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(owner);
        self.jobs
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .retain(|_, job| {
                if job.owner == owner {
                    job.fail("owning plugin unloaded");
                    crate::mesh::router().transition(&job.address, crate::mesh::NodeState::Closed, None, None);
                    false
                } else {
                    true
                }
            });
    }

    pub(crate) fn cancel_all(&self) {
        for job in self.jobs.lock().unwrap_or_else(|e| e.into_inner()).values() {
            job.fail("parent session closed or changed");
        }
    }

    pub(crate) async fn handle(
        &self,
        parent: &AgentHarness,
        owner: u64,
        cwd: &Path,
        args: Value,
    ) -> Result<Value, String> {
        let op = args
            .get("op")
            .and_then(Value::as_str)
            .ok_or("missing child op")?;
        if op == "start" {
            return self.start(parent, owner, cwd, &args).await;
        }
        self.handle_existing(owner, args)
    }

    pub(crate) fn handle_existing(&self, owner: u64, args: Value) -> Result<Value, String> {
        let op = args
            .get("op")
            .and_then(Value::as_str)
            .ok_or("missing child op")?;
        let id = args
            .get("childId")
            .and_then(Value::as_str)
            .ok_or("missing childId")?;
        let job = {
            let jobs = self.jobs.lock().unwrap_or_else(|e| e.into_inner());
            jobs.get(id)
                .filter(|job| job.owner == owner)
                .cloned()
                .ok_or("unknown childId for this plugin")?
        };
        match op {
            "poll" => {
                let mut state = job.state.lock().unwrap_or_else(|e| e.into_inner());
                let status = if state.error.is_some() {
                    "failed"
                } else if state.result.is_some() {
                    "done"
                } else {
                    "running"
                };
                // Bound each ABI response as well as the lifetime output budget.
                let mut deltas = Vec::new();
                let mut bytes = 0;
                while let Some(delta) = state.deltas.front() {
                    if !deltas.is_empty() && bytes + delta.len() > 64 * 1024 {
                        break;
                    }
                    bytes += delta.len();
                    deltas.push(state.deltas.pop_front().expect("front exists"));
                }
                // Terminal result is delivered only after queued deltas drain.
                let drained = state.deltas.is_empty();
                Ok(
                    json!({"childId":id, "status":if drained {status} else {"running"}, "deltas":deltas,
                    "turns":state.turns, "result":if drained {state.result.clone()} else {None},
                    "error":if drained {state.error.clone()} else {None}}),
                )
            }
            "cancel" | "dispose" => {
                job.fail("child cancelled");
                if op == "dispose" {
                    self.jobs
                        .lock()
                        .unwrap_or_else(|e| e.into_inner())
                        .remove(id);
                    crate::mesh::router().transition(&job.address, crate::mesh::NodeState::Closed, None, None);
                }
                Ok(
                    json!({"childId":id,"status":if op == "dispose" {"disposed"} else {"cancelled"}}),
                )
            }
            _ => Err(format!("unknown child op `{op}`")),
        }
    }

    async fn start(
        &self,
        parent: &AgentHarness,
        owner: u64,
        cwd: &Path,
        args: &Value,
    ) -> Result<Value, String> {
        let invocation_signal = evo_agent::tool_execution_scope::invocation_signal();
        if invocation_signal
            .as_ref()
            .is_some_and(CancellationToken::is_cancelled)
        {
            return Err("parent tool invocation cancelled".into());
        }
        let task = args
            .get("task")
            .and_then(Value::as_str)
            .ok_or("missing child task")?;
        let role = args
            .get("role")
            .and_then(Value::as_str)
            .unwrap_or("worker")
            .trim();
        if task.trim().is_empty() || task.len() > 20_000 || role.is_empty() || role.len() > 200 {
            return Err("child task must contain 1-20000 bytes and role 1-200 bytes".into());
        }
        let isolated = match args.get("isolation").and_then(Value::as_str) {
            None | Some("none") => false,
            Some("worktree") => true,
            Some(other) => {
                return Err(format!("unknown isolation `{other}`: use \"worktree\" or leave it out"))
            }
        };
        let turns = bounded_number(args, "maxTurns", 8, 1, 32)? as u32;
        let timeout = bounded_number(args, "timeoutSeconds", 300, 10, 1800)?;
        let tools = args
            .get("tools")
            .map(|value| {
                value
                    .as_array()
                    .ok_or("child tools must be a string array")
                    .and_then(|values| {
                        values
                            .iter()
                            .map(|v| {
                                v.as_str()
                                    .map(str::to_owned)
                                    .ok_or("child tools must be a string array")
                            })
                            .collect::<Result<Vec<_>, _>>()
                    })
            })
            .transpose()?;
        let id = parent.session().id_generator().next();
        let address = crate::mesh::Address::session(&parent.session().storage().metadata().id)
            .child(crate::mesh::NodeKind::Agent, &id);
        let job = Arc::new(Job {
            owner,
            address,
            cancel: CancellationToken::new(),
            invocation_signal,
            state: Mutex::new(State::default()),
        });
        // Reserve before awaiting construction so concurrent starts cannot exceed the cap.
        let permit;
        {
            let revoked = self.revoked.lock().unwrap_or_else(|e| e.into_inner());
            if revoked.contains(&owner) {
                return Err("owning plugin unloaded".into());
            }
            let mut jobs = self.jobs.lock().unwrap_or_else(|e| e.into_inner());
            if jobs.len() >= MAX_JOBS {
                return Err("child capacity reached; dispose finished children".into());
            }
            let mut active = self.active.load(Ordering::Acquire);
            loop {
                if active >= MAX_JOBS {
                    return Err("child cleanup still in progress; retry later".into());
                }
                match self.active.compare_exchange_weak(
                    active,
                    active + 1,
                    Ordering::AcqRel,
                    Ordering::Acquire,
                ) {
                    Ok(_) => break,
                    Err(current) => active = current,
                }
            }
            permit = Permit(self.active.clone());
            jobs.insert(id.clone(), job.clone());
        }
        // Its own worktree, made after the capacity check so a refused start leaves none.
        let worktree = if isolated {
            match create_worktree(cwd).await {
                Ok(created) => Some(created),
                Err(error) => {
                    self.jobs.lock().unwrap_or_else(|e| e.into_inner()).remove(&id);
                    return Err(format!("could not create a worktree: {error}"));
                }
            }
        } else {
            None
        };
        let replacements = worktree
            .as_ref()
            .map(|created| crate::session::builtin_tools_in(&created.cwd))
            .unwrap_or_default();
        let session = Session::new(
            Arc::new(InMemorySessionStorage::new(
                SessionMetadata {
                    id: id.clone(),
                    created_at: 0,
                    parent_session_id: Some(parent.session().storage().metadata().id.clone()),
                },
                Arc::new(SystemClock),
                Arc::new(DefaultIdGenerator::new()),
            )),
            None,
        );
        let child = match parent
            .create_child_with_tools(session, Arc::new(Emitter(job.clone())), turns, tools, replacements)
            .await
        {
            Ok(child) => child,
            Err(error) => {
                self.jobs
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .remove(&id);
                if let Some(created) = worktree {
                    let _ = finish_worktree(created, cwd.to_path_buf()).await;
                }
                return Err(error.to_string());
            }
        };
        let place = match &worktree {
            Some(created) => format!(
                " Your working folder is an isolated Git worktree at {} on branch `{}`, cut from the current commit. Make your changes there and do not commit them: the parent reviews them.",
                created.cwd.display(),
                created.worktree.branch
            ),
            None => String::new(),
        };
        let started_worktree = worktree.as_ref().map(|created| worktree_json(created, None));
        let weak = Arc::downgrade(&job);
        crate::mesh::router().spawn(
            job.address.clone(),
            role,
            crate::mesh::Origin::Plugin,
            json!({ "role": role, "plugin": owner, "maxTurns": turns, "worktree": started_worktree }),
            Some(Arc::new(move || match weak.upgrade() {
                Some(job) => {
                    let finished = {
                        let state = job.state.lock().unwrap_or_else(|e| e.into_inner());
                        state.result.is_some() || state.error.is_some()
                    };
                    job.fail("child cancelled");
                    !finished
                }
                None => false,
            })),
        );
        let repo = cwd.to_path_buf();
        let prompt = format!("You are a delegated {role} subagent. Complete the task in at most {turns} turns. Do not delegate, spawn, or ask another agent to do work. Work only in the current project and return a concise final report.{place}\n\nTask:\n{task}");
        let worker = job.clone();
        let execution_scope = child.execution_scope.clone();
        let cleanup_harness = child.harness.clone();
        tokio::spawn(async move {
            let _permit = permit;
            if std::panic::AssertUnwindSafe(run_child(
                child,
                worker.clone(),
                prompt,
                turns,
                timeout,
                worktree.map(|created| (created, repo)),
            ))
            .catch_unwind()
            .await
            .is_err()
            {
                worker.fail("child runner panicked");
                let _ = cleanup_harness.close().await;
            }
            // Also retain capacity when run_child unwinds after starting a
            // background driver; catch_unwind is not a cleanup completion.
            execution_scope.wait_idle().await;
        });
        let mut started = json!({"childId":id,"sessionId":id,"status":"running"});
        if let Some(worktree) = started_worktree {
            started["worktree"] = worktree;
        }
        Ok(started)
    }
}

/// A managed worktree of `cwd`'s repository, where Settings → Sandbox says.
pub(crate) async fn create_worktree(cwd: &Path) -> Result<crate::worktrees::Created, String> {
    let cwd = cwd.to_path_buf();
    let location = evo_tools::sandbox::policy().worktree_location();
    tokio::task::spawn_blocking(move || crate::worktrees::manager()?.create(&cwd, location))
        .await
        .map_err(|e| e.to_string())?
}

pub(crate) fn worktree_json(created: &crate::worktrees::Created, changed: Option<bool>) -> Value {
    let mut value = json!({
        "path": created.worktree.path,
        "cwd": created.cwd,
        "branch": created.worktree.branch,
        "location": created.worktree.location,
    });
    if let Some(changed) = changed {
        // A changed worktree is kept for the parent to review or merge.
        value["changed"] = json!(changed);
        value["kept"] = json!(changed);
    }
    value
}

/// After the child: remove an unchanged worktree, keep a changed one.
pub(crate) async fn finish_worktree(created: crate::worktrees::Created, repo: PathBuf) -> Value {
    tokio::task::spawn_blocking(move || {
        let changed = crate::worktrees::Worktrees::changed(&created.worktree.path, Some(&created.base));
        if !changed {
            let removed = crate::worktrees::manager().and_then(|w| w.remove(&repo, &created.worktree.path));
            if let Err(error) = removed {
                tracing::warn!("could not remove an unused child worktree: {error}");
                let mut value = worktree_json(&created, Some(false));
                value["kept"] = json!(true);
                return value;
            }
        }
        worktree_json(&created, Some(changed))
    })
    .await
    .unwrap_or(Value::Null)
}

fn bounded_number(
    args: &Value,
    key: &str,
    default: u64,
    min: u64,
    max: u64,
) -> Result<u64, String> {
    let value = match args.get(key) {
        None => default,
        Some(value) => value
            .as_u64()
            .ok_or_else(|| format!("{key} must be an integer"))?,
    };
    if !(min..=max).contains(&value) {
        return Err(format!("{key} must be between {min} and {max}"));
    }
    Ok(value)
}

async fn run_child(
    child: ChildHarness,
    job: Arc<Job>,
    prompt: String,
    turns: u32,
    timeout: u64,
    worktree: Option<(crate::worktrees::Created, PathBuf)>,
) {
    let lane = child.harness.lane("main");
    let run = lane.prompt_text(&prompt, Vec::new());
    tokio::pin!(run);
    let parent_abort = async {
        match &child.parent_signal {
            Some(signal) => signal.cancelled().await,
            None => std::future::pending::<()>().await,
        }
    };
    let invocation_abort = async {
        match &job.invocation_signal {
            Some(signal) => signal.cancelled().await,
            None => std::future::pending::<()>().await,
        }
    };
    let result = tokio::select! {
        biased;
        _ = job.cancel.cancelled() => None,
        _ = invocation_abort => {job.fail("parent tool invocation cancelled"); None},
        _ = child.scope.cancelled() => {job.fail("parent run ended"); None},
        _ = parent_abort => {job.fail("parent run cancelled"); None},
        _ = tokio::time::sleep(Duration::from_secs(timeout)) => {job.fail(format!("child timed out after {timeout} seconds")); None},
        result = &mut run => Some(result),
    };
    // Settle the worktree before the result is published, so the result says
    // whether it was kept. The child's tools stop first.
    let worktree = match worktree {
        Some((created, repo)) => {
            if !matches!(result, Some(Ok(_))) {
                let _ = lane.abort().await;
            }
            let _ = child.harness.close().await;
            Some(finish_worktree(created, repo).await)
        }
        None => None,
    };
    if let Some(result) = result {
        match result {
            Ok(result) => {
                let mut outcome = crate::extensions_actions::run_outcome_json(result.outcome);
                if let Some(worktree) = &worktree {
                    outcome["worktree"] = worktree.clone();
                }
                let mut state = job.state.lock().unwrap_or_else(|e| e.into_inner());
                let bytes = outcome
                    .get("text")
                    .and_then(Value::as_str)
                    .map_or(0, str::len);
                if state.bytes.saturating_add(bytes) > MAX_OUTPUT {
                    state
                        .error
                        .get_or_insert_with(|| "child output limit exceeded".into());
                } else if state.error.is_none() {
                    outcome["turns"] = json!(state.turns);
                    outcome["turnLimited"] = json!(state.turns >= turns);
                    state.result = Some(outcome);
                }
            }
            Err(error) => job.fail(format!("child run failed: {error}")),
        }
    } else {
        // Abort even if cancellation raced ahead of the run's first poll. A closed
        // harness rejects admission; an admitted run gets its cancellation signal.
        let _ = lane.abort().await;
        let _ = child.harness.close().await;
        let _ = tokio::time::timeout(Duration::from_secs(2), &mut run).await;
    }
    let _ = child.harness.close().await;
    announce(&job);
}

/// Tell the mesh how the child ended: its report, then the settled state.
fn announce(job: &Job) {
    use crate::mesh::{NodeState, RunStatus};
    let (status, text, reason, usage, worktree) = {
        let state = job.state.lock().unwrap_or_else(|e| e.into_inner());
        match (&state.result, &state.error) {
            (Some(result), _) => (
                RunStatus::Done,
                result.get("text").and_then(Value::as_str).unwrap_or_default().to_string(),
                None,
                state.usage,
                result.get("worktree").cloned(),
            ),
            (None, error) => {
                let reason = error.clone().unwrap_or_else(|| "child stopped".into());
                let status = if reason.contains("cancel") { RunStatus::Cancelled } else { RunStatus::Failed };
                (status, format!("The child stopped: {reason}."), Some(reason), state.usage, None)
            }
        }
    };
    let router = crate::mesh::router();
    router.report(&job.address, status, text, usage, worktree);
    router.transition(&job.address, NodeState::Settled, Some(status), reason);
}

#[cfg(test)]
mod tests;
