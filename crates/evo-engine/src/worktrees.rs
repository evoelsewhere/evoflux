//! Managed Git worktrees (the `evo-worktrees` crate), rooted in this agent
//! directory: user-data-directory worktrees live in `<agent dir>/worktrees`.

pub use evo_worktrees::*;

/// The worktree manager for this engine's agent directory.
pub fn manager() -> Result<Worktrees, String> {
    let agent = crate::config::agent_dir().map_err(|e| e.to_string())?;
    Ok(Worktrees::with_data_root(agent.join("worktrees")))
}
