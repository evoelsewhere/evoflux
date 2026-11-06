//! The built-in `skill` tool: how the model loads a skill.
//!
//! The system prompt lists every model-visible skill (`<available_skills>`,
//! name + description only). When a task matches one, the model calls
//! `skill {name, arguments?}` and gets the skill's instructions back, after
//! the same substitutions `/name args` gets (`$ARGUMENTS`, `$N` in command
//! files, `${SKILL_DIR}`), wrapped with the skill's folder so relative
//! paths resolve. The file is read fresh, so an edit applies at once. Reading
//! `SKILL.md` with the read tool keeps working.

use std::sync::Arc;

use async_trait::async_trait;
use evo_agent::agent_tool::AgentTool;
use evo_agent::error::AgentError;
use evo_agent::types::{AgentToolResult, TextContentOrImage, ToolExecutionMode, ToolResultPartial};
use evo_ai::types::{Schema, Tool};
use evo_harness::agent_harness::WeakAgentHarness;
use serde::Deserialize;
use serde_json::{json, Value};
use tokio_util::sync::CancellationToken;

use crate::agent_tool::HarnessCell;

pub struct SkillTool {
    schema: Tool,
    harness: HarnessCell,
}

#[derive(Deserialize)]
struct Input {
    name: String,
    #[serde(default)]
    arguments: Option<String>,
}

pub fn create_skill_tool(harness: HarnessCell) -> Arc<dyn AgentTool> {
    Arc::new(SkillTool {
        schema: Tool {
            name: "skill".into(),
            description: "Load a skill: specialized instructions for a kind of task. When the task matches a \
                 skill listed in <available_skills>, call this with the skill's name before doing the work, \
                 then follow the instructions it returns. Pass `arguments` when the user gave the skill \
                 input (for example the text after /name). Load a skill once per task; do not load one \
                 that does not match."
                .into(),
            parameters: Schema::new(json!({
                "type": "object",
                "properties": {
                    // No enum: skills added later must work without a reload.
                    "name": { "type": "string", "description": "The skill's name from <available_skills>." },
                    "arguments": { "type": "string", "description": "Optional input for the skill." }
                },
                "required": ["name"],
                "additionalProperties": false
            })),
            constrained_sampling: None,
        },
        harness,
    })
}

#[async_trait]
impl AgentTool for SkillTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }

    fn label(&self) -> &str {
        "skill"
    }

    fn execution_mode(&self) -> ToolExecutionMode {
        ToolExecutionMode::Parallel
    }

    async fn execute(
        &self,
        _tool_call_id: &str,
        params: Value,
        _signal: CancellationToken,
        _on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let input: Input = serde_json::from_value(params)
            .map_err(|e| AgentError::Validation(format!("skill input invalid: {e}")))?;
        let harness = self
            .harness
            .get()
            .and_then(WeakAgentHarness::upgrade)
            .ok_or_else(|| AgentError::Tool("the session is not ready".into()))?;
        let resources = harness
            .get_resources()
            .await
            .map_err(|e| AgentError::Tool(e.to_string()))?;
        let skills = resources.skills.unwrap_or_default();
        let wanted = input.name.trim().trim_start_matches('/');
        let skill = skills
            .iter()
            .find(|skill| skill.name == wanted)
            .or_else(|| {
                let mut found = skills.iter().filter(|skill| {
                    skill
                        .name
                        .rsplit_once(':')
                        .is_some_and(|(_, last)| last == wanted)
                });
                match (found.next(), found.next()) {
                    (Some(one), None) => Some(one),
                    _ => None,
                }
            })
            .cloned()
            .ok_or_else(|| {
                let names: Vec<_> = skills
                    .iter()
                    .filter(|s| !s.disable_model_invocation.unwrap_or(false))
                    .map(|s| s.name.as_str())
                    .collect();
                AgentError::Validation(format!(
                    "unknown skill `{wanted}`; available: {}",
                    if names.is_empty() {
                        "none".to_string()
                    } else {
                        names.join(", ")
                    }
                ))
            })?;
        if skill.disable_model_invocation.unwrap_or(false) {
            return Err(AgentError::Validation(format!(
                "skill `{}` can only be run by the user (/{})",
                skill.name, skill.name
            )));
        }
        let args = input.arguments.unwrap_or_default();
        crate::skill_runtime::record(&skill.name);
        // Fresh from disk, so edits apply at once; shell lines run.
        let cwd = crate::hooks::cwd()
            .or_else(|| std::env::current_dir().ok())
            .unwrap_or_default();
        let text = crate::skill_runtime::load(&skill, args.trim(), &cwd).await;
        Ok(AgentToolResult {
            content: vec![TextContentOrImage::text(text)],
            details: json!({
                "skill": {
                    "name": skill.name,
                    "description": skill.description,
                    "path": skill.file_path,
                    "arguments": args,
                }
            }),
            ..Default::default()
        })
    }
}
