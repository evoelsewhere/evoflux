//! Mirrors `packages/coding-agent/src/core/tools/grep.ts` — the built-in `grep`
//! `AgentTool`. Searches file contents for a regex/literal pattern and returns
//! matching lines with `file:line: text` (and optional `-line-` context lines).
//! Read-only — goes through the `FileSystem` trait so it runs against both
//! `OsExecutionEnv` and `InMemoryExecutionEnv`.
//!
//! Divergence from TS (documented): the TS tool **shells out to `rg`**
//! (ripgrep), parsing its `--json` stream, and re-reads files only for context
//! blocks. The Rust port implements search **in-process** via the `FileSystem`
//! trait + the `regex` crate, so the tool works against any `ExecutionEnv`
//! (including `InMemoryExecutionEnv`, which has no shell). Trade-offs: no
//! `.gitignore` awareness in v1 (only `.git/` directories are skipped; revisit
//! via the `ignore` crate for an `OsExecutionEnv`-only fast path), no
//! auto-download of a binary, and traversal order is a deterministic sorted BFS
//! rather than rg's walk order. Output shape, match/context line formats,
//! per-line + byte truncation, and the match-limit semantics match TS exactly.

use std::collections::VecDeque;
use std::path::Path;
use std::sync::Arc;

use async_trait::async_trait;
use evo_agent::agent_tool::AgentTool;
use evo_agent::error::AgentError;
use evo_agent::types::{AgentToolResult, TextContentOrImage, ToolResultPartial};
use evo_ai::types::Tool;
use schemars::JsonSchema;
use serde::Deserialize;
use tokio_util::sync::CancellationToken;

use crate::env::ExecutionEnv;
use crate::env::FileKind;
use crate::path_utils::resolve_read_tool_path;
use crate::tools::tool_context::ExecutionToolContext;
use crate::truncate::{
    format_size, truncate_head, truncate_line_default, TruncationOptions, TruncationResult,
    DEFAULT_MAX_BYTES, GREP_MAX_LINE_LENGTH,
};

/// Default max matches. Mirrors TS `grep.ts::DEFAULT_LIMIT`.
const DEFAULT_LIMIT: u32 = 100;

/// Input for the grep tool. Mirrors TS `GrepToolInput`. `camelCase` field names
/// match the TS wire schema (so `ignoreCase`/`ignore_case` deserialization lines
/// up with what the model emits).
#[derive(Debug, Clone, JsonSchema, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GrepInput {
    /// Search pattern (regex or literal string).
    pub pattern: String,
    /// Directory or file to search (default: current directory).
    #[serde(default)]
    pub path: Option<String>,
    /// Filter files by glob pattern, e.g. `*.ts` or `**/*.spec.ts`.
    #[serde(default)]
    pub glob: Option<String>,
    /// Case-insensitive search (default false).
    #[serde(default)]
    pub ignore_case: Option<bool>,
    /// Treat pattern as a literal string instead of regex (default false).
    #[serde(default)]
    pub literal: Option<bool>,
    /// Number of lines to show before and after each match (default 0).
    #[serde(default)]
    pub context: Option<u32>,
    /// Maximum number of matches to return (default 100).
    #[serde(default)]
    pub limit: Option<u32>,
}

/// Structured details for the grep tool. Mirrors TS `GrepToolDetails`.
#[derive(Debug, Clone, serde::Serialize)]
pub struct GrepToolDetails {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub truncation: Option<TruncationResult>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub match_limit_reached: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lines_truncated: Option<bool>,
}

/// Options for `create_grep_tool`. The TS tool carries an optional `operations`
/// bag for remote backends; the Rust port always uses the `FileSystem` trait, so
/// this is an empty forward-compat seam (parity with `ReadToolOptions`).
#[derive(Debug, Clone, Default)]
pub struct GrepToolOptions {}

/// The built-in `grep` tool. Holds an `Arc<dyn ExecutionEnv>` (read-only view).
pub struct GrepTool {
    schema: Tool,
    env: Arc<dyn ExecutionEnv>,
}

impl GrepTool {
    fn schema() -> Tool {
        let params = schemars::schema_for!(GrepInput);
        Tool {
            name: "grep".to_string(),
            description: format!(
                "Search file contents for a pattern. Returns matching lines with file paths and \
                 line numbers. Skips `.git/` directories. Output is truncated to {DEFAULT_LIMIT} \
                 matches or {kb}KB (whichever is hit first). Long lines are truncated to \
                 {GREP_MAX_LINE_LENGTH} chars.",
                kb = DEFAULT_MAX_BYTES / 1024
            ),
            parameters: evo_ai::types::Schema::new(
                serde_json::to_value(params).unwrap_or_default(),
            ),
            constrained_sampling: None,
        }
    }
}

/// Build the `grep` tool from a context. Mirrors TS `createGrepTool`.
pub fn create_grep_tool(
    context: &ExecutionToolContext,
    options: Option<GrepToolOptions>,
) -> Arc<dyn AgentTool> {
    let _ = options; // forward-compat seam, no surface in v1
    Arc::new(GrepTool {
        schema: GrepTool::schema(),
        env: context.env().clone(),
    })
}

#[async_trait]
impl AgentTool for GrepTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }
    fn label(&self) -> &str {
        "grep"
    }

    async fn execute(
        &self,
        _tool_call_id: &str,
        params: serde_json::Value,
        signal: CancellationToken,
        _on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let input: GrepInput = serde_json::from_value(params)
            .map_err(|e| AgentError::Validation(format!("grep input invalid: {e}")))?;

        let cancel = Some(&signal);
        let effective_limit = input.limit.unwrap_or(DEFAULT_LIMIT).max(1) as usize;
        let context_val = input.context.unwrap_or(0).min(u32::MAX) as usize;

        // Compile the regex. `literal` ⇒ escape; `ignore_case` ⇒ case-insensitive.
        let pattern = if input.literal.unwrap_or(false) {
            regex::escape(&input.pattern)
        } else {
            input.pattern.clone()
        };
        let re = regex::RegexBuilder::new(&pattern)
            .case_insensitive(input.ignore_case.unwrap_or(false))
            .build()
            .map_err(|e| AgentError::Validation(format!("grep pattern invalid: {e}")))?;

        // Compile the optional glob filter. `has_separator` decides whether to
        // match the full relative path (`**/*.ts`) or just the basename (`*.ts`),
        // mirroring rg's basename-glob leniency.
        let glob: Option<(globset::GlobMatcher, bool)> = match input.glob.as_deref() {
            Some(g) if !g.is_empty() => {
                let compiled = globset::Glob::new(g)
                    .map_err(|e| AgentError::Validation(format!("grep glob invalid: {e}")))?
                    .compile_matcher();
                Some((compiled, g.contains('/')))
            }
            _ => None,
        };

        // Resolve the search path. A `.`/absent path resolves to the env cwd.
        let search_path =
            resolve_read_tool_path(&*self.env, input.path.as_deref().unwrap_or("."), cancel)
                .await
                .map_err(file_err_to_agent)?;

        // Determine dir vs file (following a symlinked root via canonical_path).
        let info = self
            .env
            .file_info(&search_path, cancel)
            .await
            .map_err(file_err_to_agent)?;
        let root_kind = if info.kind == FileKind::Symlink {
            match self.env.canonical_path(&search_path, cancel).await {
                Ok(canon) => match self.env.file_info(&canon.to_string_lossy(), cancel).await {
                    Ok(i) => i.kind,
                    Err(_) => info.kind, // treat as whatever lstat said
                },
                Err(_) => info.kind,
            }
        } else {
            info.kind
        };

        // Mutable collection state shared across the file-search helper.
        let mut matches: usize = 0;
        let mut match_limit_reached = false;
        let mut lines_truncated = false;
        let mut output_lines: Vec<String> = Vec::new();

        if root_kind == FileKind::Directory {
            // Iterative BFS walk (avoids async-recursion boxing). Sorted entries
            // for deterministic output order.
            let mut queue: VecDeque<(String, String)> = VecDeque::new();
            queue.push_back((search_path.clone(), String::new()));
            while let Some((abs_dir, rel_dir)) = queue.pop_front() {
                if matches >= effective_limit {
                    break;
                }
                let mut entries = match self.env.list_dir(&abs_dir, cancel).await {
                    Ok(e) => e,
                    Err(_) => continue, // unreadable dir — skip (TS relies on rg to ignore)
                };
                entries.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
                for entry in entries {
                    if matches >= effective_limit {
                        match_limit_reached = true;
                        break;
                    }
                    let child_abs = entry.path.to_string_lossy().into_owned();
                    match entry.kind {
                        FileKind::Directory => {
                            // Skip `.git/` (v1 has no full .gitignore support).
                            if entry.name == ".git" {
                                continue;
                            }
                            let rel = if rel_dir.is_empty() {
                                entry.name.clone()
                            } else {
                                format!("{rel_dir}/{}", entry.name)
                            };
                            queue.push_back((child_abs, rel));
                        }
                        FileKind::File => {
                            let rel = if rel_dir.is_empty() {
                                entry.name.clone()
                            } else {
                                format!("{rel_dir}/{}", entry.name)
                            };
                            search_file(
                                &*self.env,
                                cancel,
                                &re,
                                glob.as_ref(),
                                context_val,
                                effective_limit,
                                &child_abs,
                                &rel,
                                &mut matches,
                                &mut match_limit_reached,
                                &mut lines_truncated,
                                &mut output_lines,
                            )
                            .await?;
                        }
                        FileKind::Symlink => {
                            // Skip symlinks during the walk (avoids loops). The
                            // search root symlink is followed above.
                        }
                    }
                }
            }
        } else if root_kind == FileKind::File {
            let rel = basename(&search_path);
            search_file(
                &*self.env,
                cancel,
                &re,
                glob.as_ref(),
                context_val,
                effective_limit,
                &search_path,
                &rel,
                &mut matches,
                &mut match_limit_reached,
                &mut lines_truncated,
                &mut output_lines,
            )
            .await?;
        } else {
            // Symlink root that didn't resolve to a file/dir (or not_supported).
            return Err(AgentError::Tool(format!(
                "Path is neither a file nor a directory: {search_path}"
            )));
        }

        if output_lines.is_empty() {
            return Ok(AgentToolResult {
                content: vec![TextContentOrImage::text("No matches found")],
                details: serde_json::Value::Null,
                ..Default::default()
            });
        }

        let raw_output = output_lines.join("\n");
        // Byte cap only — line cap disabled (match count already capped).
        let truncation = truncate_head(
            &raw_output,
            TruncationOptions {
                max_lines: Some(usize::MAX),
                max_bytes: None,
            },
        );
        let was_truncated = truncation.truncated;
        let mut output = truncation.content.clone();
        let mut details = GrepToolDetails {
            truncation: None,
            match_limit_reached: None,
            lines_truncated: None,
        };
        let mut notices: Vec<String> = Vec::new();
        if match_limit_reached {
            notices.push(format!(
                "{effective_limit} matches limit reached. Use limit={} for more, or refine pattern",
                effective_limit * 2
            ));
            details.match_limit_reached = Some(effective_limit as u32);
        }
        if was_truncated {
            notices.push(format!("{} limit reached", format_size(DEFAULT_MAX_BYTES)));
            details.truncation = Some(truncation);
        }
        if lines_truncated {
            notices.push(format!(
                "Some lines truncated to {GREP_MAX_LINE_LENGTH} chars. Use read tool to see full lines"
            ));
            details.lines_truncated = Some(true);
        }
        if !notices.is_empty() {
            output.push_str(&format!("\n\n[{}]", notices.join(". ")));
        }

        let details_value = serde_json::to_value(&details).unwrap_or(serde_json::Value::Null);
        Ok(AgentToolResult {
            content: vec![TextContentOrImage::text(output)],
            details: details_value,
            ..Default::default()
        })
    }
}

/// Search a single file for `re`, appending formatted match/context lines to
/// `output_lines` and bumping `matches`. Reads via the `FileSystem` trait; an
/// unreadable file (non-UTF-8, etc.) is silently skipped (a clean divergence —
/// in-process search can't match lines it can't decode).
#[allow(clippy::too_many_arguments)]
async fn search_file(
    env: &dyn ExecutionEnv,
    cancel: Option<&CancellationToken>,
    re: &regex::Regex,
    glob: Option<&(globset::GlobMatcher, bool)>,
    context_val: usize,
    effective_limit: usize,
    abs: &str,
    rel: &str,
    matches: &mut usize,
    match_limit_reached: &mut bool,
    lines_truncated: &mut bool,
    output_lines: &mut Vec<String>,
) -> Result<(), AgentError> {
    // Glob filter (basename vs full-relative-path per `has_separator`).
    if let Some((matcher, has_sep)) = glob {
        let basename = basename(abs);
        let passes = if *has_sep {
            matcher.is_match(rel)
        } else {
            matcher.is_match(&basename)
        };
        if !passes {
            return Ok(());
        }
    }

    // Read; skip on failure (non-UTF-8 / unreadable).
    let text = match env.read_text_file(abs, cancel).await {
        Ok(t) => t,
        Err(_) => return Ok(()),
    };
    // Normalize line endings, split on `\n` (mirror TS getFileLines).
    let normalized = text.replace("\r\n", "\n").replace('\r', "\n");
    let lines: Vec<&str> = normalized.split('\n').collect();

    for (idx, line) in lines.iter().enumerate() {
        if *matches >= effective_limit {
            *match_limit_reached = true;
            return Ok(());
        }
        if !re.is_match(line) {
            continue;
        }
        let line_number = idx + 1; // 1-indexed.
        *matches += 1;

        if context_val == 0 {
            // No context: emit the single match line (truncated).
            let out = truncate_line_default(line);
            if out.was_truncated {
                *lines_truncated = true;
            }
            output_lines.push(format!("{rel}:{line_number}: {}", out.text));
        } else {
            // Context block: match line uses `:`, context lines use `-`.
            let start = line_number.saturating_sub(context_val).max(1);
            let end = (line_number + context_val).min(lines.len());
            for current in start..=end {
                let text_line = lines.get(current - 1).copied().unwrap_or("");
                let out = truncate_line_default(text_line);
                if out.was_truncated {
                    *lines_truncated = true;
                }
                if current == line_number {
                    output_lines.push(format!("{rel}:{current}: {}", out.text));
                } else {
                    output_lines.push(format!("{rel}-{current}- {}", out.text));
                }
            }
        }
    }
    Ok(())
}

/// Filename component of a path string (POSIX-agnostic: splits on `/` and `\`).
fn basename(p: &str) -> String {
    Path::new(p)
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| p.to_string())
}

/// Map a `FileError` into an `AgentError::Tool` (same shape as `read.rs`).
fn file_err_to_agent(e: crate::error::FileError) -> AgentError {
    AgentError::Tool(e.to_string())
}
