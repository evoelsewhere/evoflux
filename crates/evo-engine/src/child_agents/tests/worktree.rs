//! `"isolation": "worktree"`: the child's tools work in its own worktree; a
//! changed worktree is kept and reported, an unchanged one is removed.

use super::*;
use evo_ai::providers::faux::{FauxProvider, FauxScript};
use evo_harness::types::AgentHarnessOptions;

fn git(dir: &Path, args: &[&str]) -> bool {
    std::process::Command::new("git")
        .arg("-C")
        .arg(dir)
        .args(args)
        .output()
        .map(|out| out.status.success())
        .unwrap_or(false)
}

/// A one-commit repository; `None` without git.
fn repo() -> Option<(tempfile::TempDir, PathBuf)> {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("project");
    std::fs::create_dir_all(&root).unwrap();
    if !git(&root, &["init", "-q"]) {
        eprintln!("skipping: git is not available");
        return None;
    }
    std::fs::write(root.join("README.md"), "hello\n").unwrap();
    for args in [
        &["config", "user.email", "evo@example.invalid"][..],
        &["config", "user.name", "evo"],
        &["add", "."],
        &["commit", "-q", "-m", "init"],
    ] {
        assert!(git(&root, args));
    }
    Some((dir, root))
}

/// A parent whose built-in tools work in `cwd`, driven by `script`.
async fn parent_in(cwd: &Path, script: FauxScript) -> AgentHarness {
    let provider = FauxProvider::new(script);
    let tools = crate::session::builtin_tools_in(cwd);
    let active_tool_names = tools.iter().map(|tool| tool.tool.schema().name.clone()).collect();
    let session = Session::new(
        Arc::new(InMemorySessionStorage::new(
            SessionMetadata { id: "parent".into(), created_at: 0, parent_session_id: None },
            Arc::new(SystemClock),
            Arc::new(DefaultIdGenerator::new()),
        )),
        None,
    );
    AgentHarness::create(AgentHarnessOptions {
        model: provider.default_model().clone(),
        models: vec![provider],
        tools,
        active_tool_names,
        session,
        ..Default::default()
    })
    .await
    .unwrap()
}

async fn finish(manager: &ChildAgents, parent: &AgentHarness, id: &str) -> Value {
    tokio::time::timeout(Duration::from_secs(20), async {
        loop {
            let value = manager
                .handle(parent, 7, Path::new("."), json!({"op":"poll","childId":id}))
                .await
                .unwrap();
            if value["status"] != "running" {
                return value;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("child must finish")
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_child_writes_in_its_own_worktree_which_is_kept() {
    // Managed worktrees go to the user data directory: use a private one.
    let _agent = crate::config::test_support::AgentDirEnv::new();
    let Some((_dir, root)) = repo() else { return };
    let script = FauxScript::new()
        .with_tool_call("write", json!({"path":"from-child.txt","content":"made by the child\n"}))
        .with_text("wrote the file");
    let parent = parent_in(&root, script).await;
    let manager = ChildAgents::default();
    let started = manager
        .handle(&parent, 7, &root, json!({"op":"start","task":"write a file","isolation":"worktree"}))
        .await
        .unwrap();
    let path = PathBuf::from(started["worktree"]["path"].as_str().unwrap());
    assert!(path.starts_with(_agent.path()), "worktrees go to the user data directory: {started}");
    assert!(started["worktree"]["branch"].as_str().unwrap().starts_with(crate::worktrees::BRANCH_PREFIX));

    let done = finish(&manager, &parent, started["childId"].as_str().unwrap()).await;
    assert_eq!(done["status"], "done", "{done}");
    let worktree = &done["result"]["worktree"];
    assert_eq!((worktree["changed"].as_bool(), worktree["kept"].as_bool()), (Some(true), Some(true)), "{done}");
    // The file is in the worktree, not in the parent's checkout.
    assert_eq!(std::fs::read_to_string(path.join("from-child.txt")).unwrap(), "made by the child\n");
    assert!(!root.join("from-child.txt").exists());
    // Listed until removed.
    let worktrees = crate::worktrees::manager().unwrap();
    assert_eq!(worktrees.list(&root).unwrap().len(), 1);
    worktrees.remove(&root, &path).unwrap();
    assert!(!path.exists());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn an_unchanged_worktree_is_removed_when_the_child_finishes() {
    // Managed worktrees go to the user data directory: use a private one.
    let _agent = crate::config::test_support::AgentDirEnv::new();
    let Some((_dir, root)) = repo() else { return };
    let parent = parent_in(&root, FauxScript::new().with_text("nothing to change")).await;
    let manager = ChildAgents::default();
    let started = manager
        .handle(&parent, 7, &root, json!({"op":"start","task":"look around","isolation":"worktree"}))
        .await
        .unwrap();
    let path = PathBuf::from(started["worktree"]["path"].as_str().unwrap());
    assert!(path.exists());
    let done = finish(&manager, &parent, started["childId"].as_str().unwrap()).await;
    assert_eq!(done["result"]["worktree"]["kept"], json!(false), "{done}");
    assert!(!path.exists());
    assert!(crate::worktrees::manager().unwrap().list(&root).unwrap().is_empty());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn worktree_isolation_needs_a_repository_and_a_known_mode() {
    let dir = tempfile::tempdir().unwrap();
    let parent = parent_in(dir.path(), FauxScript::new().with_text("x")).await;
    let manager = ChildAgents::default();
    let error = manager
        .handle(&parent, 7, dir.path(), json!({"op":"start","task":"t","isolation":"worktree"}))
        .await
        .unwrap_err();
    assert!(error.contains("could not create a worktree"), "{error}");
    assert!(manager.jobs.lock().unwrap().is_empty(), "a refused start leaves no job");
    let error = manager
        .handle(&parent, 7, dir.path(), json!({"op":"start","task":"t","isolation":"container"}))
        .await
        .unwrap_err();
    assert!(error.contains("unknown isolation"), "{error}");
}
