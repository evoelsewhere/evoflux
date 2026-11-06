//! Mirrors `packages/agent/src/harness/utils/shell-output.ts` — the bash tool's
//! output-capture layer wrapping `Shell::exec`.
//!
//! Combines stdout+stderr into a single rolling tail buffer (capped at
//! twice the inline limit — `DEFAULT_MAX_BYTES`, or the sandbox's
//! `max_output_kib`), spills to a temp file (`bash-*.log`) once cumulative
//! output exceeds the inline limit or `DEFAULT_MAX_LINES`,
//! and produces a [`ShellCaptureResult`] carrying truncation metadata + the
//! temp-file path. `on_chunk` fires per sanitized/CR-stripped chunk with a
//! progress snapshot.
//!
//! `return_execution_errors: true` causes exec failures to come back as a
//! success-result with `execution_error` populated (so the bash tool — not the
//! env — owns error rendering via `append_status`). There is NO time-based
//! throttle here; throttling lives in the bash tool.
//!
//! **v1 divergence from the TS:** the TS initializes the temp file mid-stream
//! (inside the stdout/stderr callback) and appends subsequent chunks. Doing
//! async file I/O from a sync `FnMut` callback is unsound in Rust, so the v1
//! port performs the spill in a single **post-stream** pass: the entire
//! captured tail is written to the temp file after `exec` resolves. The
//! `full_output_path` and truncation metadata are identical; only the timing
//! of the file write differs. Tests verify the temp file exists when output
//! exceeds limits — they don't depend on mid-stream creation.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

use crate::env::{ExecutionEnv, FileContent, ShellExecOptions};
use crate::error::{ExecutionError, ExecutionErrorCode};
use crate::truncate::{
    trim_to_last_utf8_bytes, truncate_tail, TruncationLimit, TruncationOptions, TruncationResult,
    DEFAULT_MAX_LINES,
};

/// Bytes shown inline: the sandbox's limit (`DEFAULT_MAX_BYTES` unless set).
fn inline_limit() -> usize {
    crate::sandbox::policy().max_output_bytes()
}

/// Mirrors `ShellCaptureProgress`.
#[derive(Clone)]
pub struct ShellCaptureProgress {
    pub output: String,
    pub truncation: TruncationResult,
    pub full_output_path: Option<PathBuf>,
    pub last_line_bytes: usize,
}

/// Mirrors `ShellCaptureResult`.
#[derive(Clone)]
pub struct ShellCaptureResult {
    pub output: String,
    pub truncation: TruncationResult,
    pub full_output_path: Option<PathBuf>,
    pub last_line_bytes: usize,
    pub exit_code: Option<i32>,
    pub cancelled: bool,
    pub truncated: bool,
    pub execution_error: Option<ExecutionError>,
}

/// Mirrors `ShellCaptureOptions`.
pub struct ShellCaptureOptions<'a> {
    pub shell: Option<crate::env::ShellOverride>,
    pub cwd: Option<PathBuf>,
    pub env: Option<HashMap<String, String>>,
    pub inherit_env: bool,
    pub timeout: Option<f64>,
    pub cancel: Option<&'a CancellationToken>,
    pub on_chunk: Option<Box<dyn FnMut(&str, &dyn Fn() -> ShellCaptureProgress) + Send + 'a>>,
    pub return_execution_errors: bool,
}

impl<'a> Default for ShellCaptureOptions<'a> {
    fn default() -> Self {
        Self {
            shell: None,
            cwd: None,
            env: None,
            inherit_env: true,
            timeout: None,
            cancel: None,
            on_chunk: None,
            return_execution_errors: false,
        }
    }
}

/// Shared capture state, mutated by the stdout/stderr closures and read by the
/// post-stream progress computation.
#[derive(Default)]
struct CaptureState {
    tail_output: String,
    total_bytes: usize,
    completed_lines: usize,
    has_open_line: bool,
    current_line_bytes: usize,
    full_output_path: Option<PathBuf>,
    full_output_requested: bool,
}

impl CaptureState {
    fn ingest_chunk(&mut self, text: &str) {
        let text_bytes = text.len();
        self.total_bytes += text_bytes;
        let newline_count = text.matches('\n').count();
        self.completed_lines += newline_count;
        let last_newline = text.rfind('\n');
        match last_newline {
            Some(idx) => {
                let trailing = &text[idx + 1..];
                self.current_line_bytes = trailing.len();
                self.has_open_line = !trailing.is_empty();
            }
            None if !text.is_empty() => {
                self.current_line_bytes += text_bytes;
                self.has_open_line = true;
            }
            None => {}
        }
        self.tail_output.push_str(text);
        // Cap the in-memory tail at twice the inline limit.
        let trimmed = trim_to_last_utf8_bytes(&self.tail_output, inline_limit() * 2);
        if trimmed.len() != self.tail_output.len() {
            self.tail_output = trimmed.to_string();
        }
    }

    fn create_progress(&self) -> ShellCaptureProgress {
        let max_bytes = inline_limit();
        let tail_truncation = truncate_tail(
            &self.tail_output,
            TruncationOptions { max_lines: None, max_bytes: Some(max_bytes) },
        );
        let total_lines = self.completed_lines + if self.has_open_line { 1 } else { 0 };
        let truncated = total_lines > DEFAULT_MAX_LINES || self.total_bytes > max_bytes;
        let truncated_by = if truncated {
            tail_truncation
                .truncated_by
                .or(if self.total_bytes > max_bytes {
                    Some(TruncationLimit::Bytes)
                } else {
                    Some(TruncationLimit::Lines)
                })
        } else {
            None
        };
        let truncation = TruncationResult {
            truncated,
            truncated_by,
            total_lines,
            total_bytes: self.total_bytes,
            ..tail_truncation
        };
        let output = if truncated {
            truncation.content.clone()
        } else {
            self.tail_output.clone()
        };
        ShellCaptureProgress {
            output,
            truncation,
            full_output_path: self.full_output_path.clone(),
            last_line_bytes: self.current_line_bytes,
        }
    }
}

/// Sanitize a chunk: drop C0 controls (except TAB/LF/CR) and interlinear
/// annotation chars (U+FFF9..U+FFFB), then strip all CR. Mirrors
/// `sanitizeBinaryOutput` + the per-chunk `.replace(/\r/g, "")`.
///
/// ANSI escape sequences are consumed whole rather than having just their
/// leading ESC byte (a C0 control) dropped: dropping only ESC left the
/// sequence body behind, so colored output (e.g. `vite` build logs) surfaced
/// as literal `[36m`-style garbage in the tool response.
fn sanitize_and_strip_cr(chunk: &str) -> String {
    let mut out = String::with_capacity(chunk.len());
    let mut chars = chunk.chars().peekable();
    while let Some(c) = chars.next() {
        let u = c as u32;
        if c == '\x1b' {
            skip_escape_sequence(&mut chars);
        } else if u == 0x09 || u == 0x0a || u == 0x0d {
            out.push(c);
        } else if u <= 0x1f {
            // other C0 controls → drop
        } else if (0xfff9..=0xfffb).contains(&u) {
            // interlinear annotation → drop
        } else {
            out.push(c);
        }
    }
    out.replace('\r', "")
}

/// Consume one ANSI escape sequence, starting just after the ESC byte the
/// caller already read. Handles CSI (`ESC [ … final`), OSC (`ESC ] … BEL |
/// `ESC \`), and charset designators (`ESC ( X`); any other escape swallows a
/// single following char.
fn skip_escape_sequence(chars: &mut std::iter::Peekable<std::str::Chars<'_>>) {
    match chars.peek() {
        Some('[') => {
            chars.next();
            // CSI: parameter/intermediate bytes, terminated by a final byte in
            // the 0x40..=0x7E range.
            while let Some(c) = chars.next() {
                if (0x40..=0x7e).contains(&(c as u32)) {
                    break;
                }
            }
        }
        Some(']') => {
            chars.next();
            // OSC: terminated by BEL (0x07) or ST (ESC \).
            while let Some(c) = chars.next() {
                if c == '\x07' {
                    break;
                }
                if c == '\x1b' {
                    if let Some('\\') = chars.peek() {
                        chars.next();
                    }
                    break;
                }
            }
        }
        Some('(') | Some(')') => {
            // Charset designator: ESC ( or ESC ) followed by one char.
            chars.next();
            chars.next();
        }
        Some(_) => {
            chars.next();
        }
        None => {}
    }
}

/// Mirrors `executeShellWithCapture`. Drives `env.exec` with on_stdout/on_stderr
/// callbacks that fold into [`CaptureState`], spills to a temp file in a
/// post-stream pass, and returns the terminal [`ShellCaptureResult`].
pub async fn execute_shell_with_capture(
    env: &Arc<dyn ExecutionEnv>,
    command: &str,
    options: ShellCaptureOptions<'_>,
) -> Result<ShellCaptureResult, ExecutionError> {
    let state = Arc::new(Mutex::new(CaptureState::default()));

    // The user on_chunk callback. Both streams fire it (the TS wires both to the
    // same onChunk); we share it via Arc<Mutex<Option<Box>>> so both closures can
    // call it without moving the Box twice.
    let user_cb: Arc<
        Mutex<Option<Box<dyn FnMut(&str, &dyn Fn() -> ShellCaptureProgress) + Send>>>,
    > = Arc::new(Mutex::new(options.on_chunk));

    let state_stdout = state.clone();
    let user_cb_stdout = user_cb.clone();
    let on_stdout: Box<dyn FnMut(&str) + Send> = Box::new(move |chunk: &str| {
        let text = sanitize_and_strip_cr(chunk);
        // Snapshot the progress BEFORE ingest so on_chunk sees the pre-chunk
        // state? The TS calls onChunk after updating, with the post-chunk
        // progress. We match: ingest first, then snapshot.
        let snap = {
            let mut s = match state_stdout.try_lock() {
                Ok(g) => g,
                Err(_) => return, // contention — skip this chunk's callback
            };
            s.ingest_chunk(&text);
            s.create_progress()
        };
        let mut cbg = match user_cb_stdout.try_lock() {
            Ok(g) => g,
            Err(_) => return,
        };
        if let Some(cb) = cbg.as_mut() {
            // The TS onChunk receives (chunk_text, getProgress). We pass the
            // snapshot getter as a closure returning the already-captured value.
            let snap = snap.clone();
            let getter = move || snap.clone();
            cb(chunk, &getter);
        }
    });

    let state_stderr = state.clone();
    let user_cb_stderr = user_cb.clone();
    let on_stderr: Box<dyn FnMut(&str) + Send> = Box::new(move |chunk: &str| {
        let text = sanitize_and_strip_cr(chunk);
        let snap = {
            let mut s = match state_stderr.try_lock() {
                Ok(g) => g,
                Err(_) => return,
            };
            s.ingest_chunk(&text);
            s.create_progress()
        };
        let mut cbg = match user_cb_stderr.try_lock() {
            Ok(g) => g,
            Err(_) => return,
        };
        if let Some(cb) = cbg.as_mut() {
            let snap = snap.clone();
            let getter = move || snap.clone();
            cb(chunk, &getter);
        }
    });

    let exec_opts = ShellExecOptions {
        shell: options.shell.clone(),
        cwd: options.cwd.clone(),
        env: options.env.clone(),
        inherit_env: options.inherit_env,
        timeout: options.timeout,
        cancel: options.cancel,
        on_stdout: Some(on_stdout),
        on_stderr: Some(on_stderr),
    };

    let exec_result = env.exec(command, exec_opts).await;

    // Post-stream safety net: if truncated and no temp file yet, init it now
    // with the captured tail.
    {
        let progress = state.lock().await.create_progress();
        if progress.truncation.truncated {
            let s = state.lock().await;
            if !s.full_output_requested {
                let initial = s.tail_output.clone();
                drop(s);
                match init_full_output_file(env.clone(), &initial, options.cancel).await {
                    Ok(path) => {
                        let mut s2 = state.lock().await;
                        s2.full_output_path = Some(path);
                        s2.full_output_requested = true;
                    }
                    Err(e) => {
                        // Spill failure is non-fatal — the capture still
                        // returns; the truncation metadata is present, just no
                        // fullOutputPath. Log via tracing.
                        tracing::warn!("bash full-output temp file init failed: {e}");
                    }
                }
            }
        }
    }

    let progress = state.lock().await.create_progress();
    // Pull the scalar/move fields out once so we never read a partially-moved
    // `progress` (e.g. `progress.truncation.truncated` after `truncation:` moved it).
    let ShellCaptureProgress {
        output,
        truncation,
        full_output_path,
        last_line_bytes,
    } = progress;
    let truncated_flag = truncation.truncated;
    match exec_result {
        Ok(out) => {
            let cancelled = options.cancel.map(|t| t.is_cancelled()).unwrap_or(false);
            Ok(ShellCaptureResult {
                output: output.clone(),
                truncation: truncation.clone(),
                full_output_path: full_output_path.clone(),
                last_line_bytes,
                exit_code: if cancelled { None } else { Some(out.exit_code) },
                cancelled,
                truncated: truncated_flag,
                execution_error: None,
            })
        }
        Err(e) => {
            let is_aborted = e.code == ExecutionErrorCode::Aborted
                || options.cancel.map(|t| t.is_cancelled()).unwrap_or(false);
            if is_aborted {
                Ok(ShellCaptureResult {
                    output,
                    truncation,
                    full_output_path,
                    last_line_bytes,
                    exit_code: None,
                    cancelled: true,
                    truncated: truncated_flag,
                    execution_error: None,
                })
            } else if options.return_execution_errors {
                Ok(ShellCaptureResult {
                    output,
                    truncation,
                    full_output_path,
                    last_line_bytes,
                    exit_code: None,
                    cancelled: false,
                    truncated: truncated_flag,
                    execution_error: Some(e),
                })
            } else {
                Err(e)
            }
        }
    }
}

/// Create the temp file with initial content. Mirrors `ensureFullOutputFile`'s
/// first-call path: `env.createTempFile({prefix:"bash-", suffix:".log"})` +
/// `appendFile(path, initialContent)`.
async fn init_full_output_file(
    env: Arc<dyn ExecutionEnv>,
    initial: &str,
    cancel: Option<&CancellationToken>,
) -> Result<PathBuf, ExecutionError> {
    let path = env
        .create_temp_file("bash-", ".log", cancel)
        .await
        .map_err(|e| ExecutionError::new(ExecutionErrorCode::Unknown, e.to_string()))?;
    env.append_file(
        &path.to_string_lossy(),
        FileContent::Text(initial.to_string()),
        cancel,
    )
    .await
    .map_err(|e| ExecutionError::new(ExecutionErrorCode::Unknown, e.to_string()))?;
    Ok(path)
}

/// Re-export `format_size` for the bash tool's truncation footer messages.
pub use crate::truncate::format_size;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_strips_controls_keeps_tab_lf() {
        let s = "a\x01b\tc\nd\x0be";
        let out = sanitize_and_strip_cr(&s);
        assert_eq!(out, "ab\tc\nde");
    }

    #[test]
    fn sanitize_strips_cr() {
        let s = "a\r\nb\rc";
        let out = sanitize_and_strip_cr(&s);
        assert_eq!(out, "a\nbc");
    }

    #[test]
    fn sanitize_strips_interlinear_annotation() {
        let s = "a\u{fff9}b\u{fffb}c";
        let out = sanitize_and_strip_cr(&s);
        assert_eq!(out, "abc");
    }

    #[test]
    fn sanitize_strips_full_ansi_sequences() {
        // Regression: dropping only the ESC byte used to leave `[36m`-style
        // literal garbage in the captured/output text.
        let s = "\x1b[36mvite v6.4.3\x1b[39m \x1b[32m\u{2713}\x1b[39m built\n";
        assert_eq!(sanitize_and_strip_cr(s), "vite v6.4.3 \u{2713} built\n");
        let s = "a\x1b[1m\x1b[2mX\x1b[22m\x1b[22mb";
        assert_eq!(sanitize_and_strip_cr(s), "aXb");
    }

    #[test]
    fn sanitize_strips_osc_sequences() {
        assert_eq!(sanitize_and_strip_cr("a\x1b]0;title\x07b"), "ab");
        assert_eq!(sanitize_and_strip_cr("a\x1b]8;;http://x\x1b\\b"), "ab");
    }

    #[test]
    fn capture_state_ingest_and_progress() {
        let mut s = CaptureState::default();
        s.ingest_chunk("line1\nline2\n");
        s.ingest_chunk("line3");
        let p = s.create_progress();
        // 3 lines total (line1, line2, line3-open).
        assert_eq!(p.truncation.total_lines, 3);
        assert!(!p.truncation.truncated);
        assert_eq!(p.output, "line1\nline2\nline3");
    }
}
