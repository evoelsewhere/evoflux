//! What fills the model's context window, by category, for the desktop's
//! context panel.
//!
//! The total comes from the harness's estimate: the provider's last reported
//! prompt size plus what was added since, or a character estimate before the
//! first reply. The fixed parts of every request — the system prompt and the
//! files folded into it, the skills listing, the tool definitions — are
//! measured with the same characters-per-token heuristic the compactor uses,
//! and the conversation is what remains. Categories therefore always add up to
//! the total the header shows.

use std::sync::Arc;

use evo_harness::agent_harness::{AgentHarness, AgentLane};
use serde_json::{json, Value};

/// `ceil(chars / 4)`, the compactor's estimate.
fn tokens(text: &str) -> i64 {
    (text.chars().count() as i64 + 3) / 4
}

fn tool_tokens(tool: &evo_ai::Tool) -> i64 {
    tokens(&tool.name) + tokens(&tool.description) + tokens(&tool.parameters.as_value().to_string())
}

/// `get_context_breakdown`.
pub async fn breakdown(
    lane: &Arc<dyn AgentLane>,
    harness: &AgentHarness,
    snapshot: Option<&Arc<evo_extensions::RegistrySnapshot>>,
) -> Value {
    use evo_harness::compaction::{build_session_context, estimate_context_tokens};
    use evo_harness::session::types::{BranchBounds, EntryOrder, EntryQuery};

    let estimate = match harness.context_usage().await {
        Ok(Some(estimate)) => estimate,
        Ok(None) => {
            let entries = harness
                .find_entries_on_branch(
                    &EntryQuery {
                        order: Some(EntryOrder::OldestFirst),
                        ..Default::default()
                    },
                    &BranchBounds::default(),
                )
                .await
                .unwrap_or_default();
            estimate_context_tokens(&build_session_context(&entries).messages)
        }
        Err(_) => estimate_context_tokens(&[]),
    };
    // A provider-reported size already includes the system prompt and tools.
    let reported = estimate.last_usage_index.is_some();
    let window = lane
        .get_model()
        .await
        .ok()
        .map(|model| model.context_window as i64)
        .unwrap_or(0);
    let settings = harness.compaction_settings();

    // ---- tools ----
    let active = lane.get_active_tools().await.unwrap_or_default();
    let plugin_names: std::collections::HashSet<String> = snapshot
        .map(|snapshot| {
            snapshot
                .tools()
                .iter()
                .map(|tool| tool.tool.name.clone())
                .collect()
        })
        .unwrap_or_default();
    let mut tools: Vec<(String, i64, bool)> = harness
        .get_tools()
        .await
        .unwrap_or_default()
        .iter()
        .map(|tool| tool.tool.schema())
        .filter(|schema| active.is_empty() || active.contains(&schema.name))
        .map(|schema| {
            (
                schema.name.clone(),
                tool_tokens(schema),
                plugin_names.contains(&schema.name),
            )
        })
        .collect();
    tools.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    let builtin_tools: i64 = tools.iter().filter(|t| !t.2).map(|t| t.1).sum();
    let plugin_tools: i64 = tools.iter().filter(|t| t.2).map(|t| t.1).sum();

    // ---- skills (listed only when the model can read them) ----
    let resources = harness
        .get_resources()
        .await
        .unwrap_or_else(|_| evo_harness::types::AgentHarnessResources::empty());
    let readable = active.is_empty() || active.iter().any(|name| name == "read");
    let skills: Vec<(String, i64)> = if readable {
        resources
            .skills
            .as_deref()
            .unwrap_or(&[])
            .iter()
            .filter(|skill| skill.disable_model_invocation != Some(true))
            .map(|skill| {
                let listing = evo_harness::system_prompt::compose_system_prompt(
                    None,
                    std::slice::from_ref(skill),
                    None,
                    None,
                );
                (skill.name.clone(), tokens(&listing))
            })
            .collect()
    } else {
        Vec::new()
    };
    let skill_tokens: i64 = skills.iter().map(|s| s.1).sum();

    // ---- system prompt and the files folded into it ----
    let base = harness
        .get_system_prompt()
        .await
        .ok()
        .flatten()
        .unwrap_or_default();
    let base_tokens = tokens(&base);
    let files: Vec<(String, i64)> = resources
        .context_files
        .iter()
        .filter_map(|path| {
            std::fs::read_to_string(path)
                .ok()
                .map(|text| (path.clone(), tokens(&text)))
        })
        .collect();
    let file_tokens: i64 = files.iter().map(|f| f.1).sum::<i64>().min(base_tokens);
    let system_tokens = base_tokens - file_tokens;

    let overhead = system_tokens + file_tokens + skill_tokens + builtin_tools + plugin_tools;
    let (total, messages) = if reported {
        (
            estimate.tokens.max(overhead),
            (estimate.tokens - overhead).max(0),
        )
    } else {
        (estimate.tokens + overhead, estimate.tokens)
    };
    let reserve = if settings.enabled {
        settings.reserve_tokens
    } else {
        0
    };
    let free = (window - total - reserve).max(0);
    let percent = |value: i64| {
        if window > 0 {
            (value as f64) * 100.0 / (window as f64)
        } else {
            0.0
        }
    };
    let category = |id: &str, label: &str, value: i64| json!({"id": id, "label": label, "tokens": value, "percent": (percent(value) * 10.0).round() / 10.0});

    json!({
        "window": window,
        "total": total,
        "percent": (percent(total) * 10.0).round() / 10.0,
        "estimated": !reported,
        "compactionEnabled": settings.enabled,
        "untilCompact": if settings.enabled && window > 0 { Some((window - reserve - total).max(0)) } else { None },
        "categories": [
            category("messages", "Messages", messages),
            category("system_tools", "System tools", builtin_tools),
            category("plugin_tools", "Plugin tools", plugin_tools),
            category("system_prompt", "System prompt", system_tokens),
            category("context_files", "Context files", file_tokens),
            category("skills", "Skills", skill_tokens),
            category("autocompact_buffer", "Autocompact buffer", reserve),
            category("free", "Free space", free),
        ],
        "tools": tools.iter().map(|(name, value, plugin)| json!({"name": name, "tokens": value, "source": if *plugin { "plugin" } else { "builtin" }})).collect::<Vec<_>>(),
        "skills": skills.iter().map(|(name, value)| json!({"name": name, "tokens": value})).collect::<Vec<_>>(),
        "contextFiles": files.iter().map(|(path, value)| json!({"path": path, "tokens": value})).collect::<Vec<_>>(),
    })
}
