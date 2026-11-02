//! `grep`: search file contents by regex (`grep.py`).
//!
//! This is the port of Python's own scan (`_python_scan_sync`), which Python
//! uses whenever ripgrep is not installed. It does not start `rg`, so a
//! sidecar that bundles ripgrep orders and filters some results differently;
//! see `server/KNOWN_DIFFERENCES.md`.

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use fancy_regex::Regex;
use serde_json::{json, Value};

use crate::args::{self, Field, Kind, Val};
use crate::fnmatch::fnmatch;
use crate::fsutil::{children, is_dir, is_file, is_symlink, mtime_ns, read_capped};
use crate::ignore::{is_skipped_dir, Rules};
use crate::pyfmt::{char_prefix, splitlines};
use crate::sandbox::{resolve, Sandbox};
use crate::{definition, property, run_blocking, search_root, Tool, ToolCtx, ToolOutput};

pub(crate) struct GrepTool;

const MAX_PATTERN_LEN: usize = 500;
const SCAN_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_LINE_CHARS: usize = 200;
const MAX_CONTEXT: i64 = 10;
const MAX_PAGE: i64 = 1000;
/// Files larger than this are skipped rather than read whole.
const MAX_FILE_BYTES: usize = 64 * 1024 * 1024;
const MODES: &[&str] = &["content", "files_with_matches", "count"];

/// Globs for the ripgrep type names the Python fallback understands.
const TYPE_GLOBS: [(&str, &[&str]); 22] = [
    ("c", &["*.c", "*.h"]),
    (
        "cpp",
        &["*.cpp", "*.cc", "*.cxx", "*.hpp", "*.hh", "*.hxx", "*.h"],
    ),
    ("cs", &["*.cs"]),
    ("css", &["*.css", "*.scss", "*.sass", "*.less"]),
    ("go", &["*.go"]),
    ("html", &["*.html", "*.htm"]),
    ("java", &["*.java"]),
    ("js", &["*.js", "*.jsx", "*.mjs", "*.cjs", "*.vue"]),
    ("json", &["*.json"]),
    ("kotlin", &["*.kt", "*.kts"]),
    ("markdown", &["*.md", "*.markdown", "*.mdx"]),
    ("md", &["*.md", "*.markdown", "*.mdx"]),
    ("php", &["*.php"]),
    ("py", &["*.py", "*.pyi"]),
    ("ruby", &["*.rb"]),
    ("rust", &["*.rs"]),
    ("sh", &["*.sh", "*.bash", "*.zsh"]),
    ("sql", &["*.sql"]),
    ("swift", &["*.swift"]),
    ("toml", &["*.toml"]),
    ("ts", &["*.ts", "*.tsx", "*.mts", "*.cts"]),
    ("yaml", &["*.yaml", "*.yml"]),
];

const DESCRIPTION: &str = "Search file contents by regex (ripgrep). output_mode 'content' \
(default) returns 'file:line: text'; 'files_with_matches' returns only \
paths, newest first — start there to locate code; 'count' returns \
matching lines per file plus a total. Filter with include (filename \
glob) or type (e.g. 'py'). A partial page ends with a notice giving \
the offset for the next page. Preferred over shell grep or rg for \
searching file contents.";

fn fields() -> Vec<Field> {
    vec![
        Field::required("pattern", Kind::Str),
        Field::optional("directory", Kind::Str, Val::Str(".".into())),
        Field::optional("include", Kind::Str, Val::Str("*".into())),
        Field::optional("type", Kind::Str, Val::Str(String::new())),
        Field::optional(
            "output_mode",
            Kind::Literal(MODES),
            Val::Str("content".into()),
        ),
        Field::optional("max_results", Kind::Int, Val::Int(100)),
        Field::optional("offset", Kind::Int, Val::Int(0)),
        Field::optional("case_insensitive", Kind::Bool, Val::Bool(false)),
        Field::optional("fixed_strings", Kind::Bool, Val::Bool(false)),
        Field::optional("multiline", Kind::Bool, Val::Bool(false)),
        Field::optional("context", Kind::Int, Val::Int(0)),
    ]
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Mode {
    Content,
    FilesWithMatches,
    Count,
}

pub(crate) struct Query<'a> {
    pub(crate) pattern: &'a str,
    pub(crate) directory: &'a str,
    pub(crate) include: &'a str,
    pub(crate) file_type: &'a str,
    pub(crate) output_mode: &'a str,
    pub(crate) max_results: i64,
    pub(crate) offset: i64,
    pub(crate) case_insensitive: bool,
    pub(crate) fixed_strings: bool,
    pub(crate) multiline: bool,
    pub(crate) context: i64,
}

/// `(is_match, display path, 1-based line number, text)`; `None` separates blocks.
type Entry = Option<(bool, String, usize, String)>;

struct Hits {
    entries: Vec<Entry>,
    files: Vec<(PathBuf, usize)>,
    complete: bool,
}

/// Whether a line-oriented regex asks to cross a line boundary.
fn contains_line_break_expression(pattern: &str) -> bool {
    if pattern.contains(['\n', '\r']) {
        return true;
    }
    // An odd run of backslashes before `n` or `r` is an escape for a line break.
    let mut run = 0usize;
    for c in pattern.chars() {
        if c == '\\' {
            run += 1;
            continue;
        }
        if run % 2 == 1 && matches!(c, 'n' | 'r') {
            return true;
        }
        run = 0;
    }
    false
}

fn valid_type_name(name: &str) -> bool {
    let length = name.chars().count();
    (1..=32).contains(&length)
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '+' | '-'))
}

fn type_globs(file_type: &str) -> Result<Option<&'static [&'static str]>, String> {
    if file_type.is_empty() {
        return Ok(None);
    }
    let lowered = file_type.to_lowercase();
    match TYPE_GLOBS.iter().find(|(name, _)| *name == lowered) {
        Some((_, globs)) => Ok(Some(globs)),
        None => {
            let names: Vec<&str> = TYPE_GLOBS.iter().map(|(name, _)| *name).collect();
            Err(format!(
                "Unknown type '{file_type}'. Use one of {}, or filter with include.",
                names.join(", ")
            ))
        }
    }
}

/// Indexes of the lines a match touches; multiline matches mark every line they span.
fn matched_line_indexes(
    regex: &Regex,
    text: &str,
    lines: &[crate::pyfmt::Line<'_>],
    multiline: bool,
    deadline: Instant,
) -> Result<Vec<usize>, String> {
    if !multiline {
        let mut found = Vec::new();
        for (i, line) in lines.iter().enumerate() {
            if deadline_due(i) {
                check_deadline(deadline)?;
            }
            if regex.is_match(line.body).map_err(|_| timeout_message())? {
                found.push(i);
            }
        }
        return Ok(found);
    }
    // Start offset of each line within `text`.
    let mut starts = vec![0usize];
    for line in lines.iter().take(lines.len().saturating_sub(1)) {
        starts.push(starts.last().copied().unwrap_or(0) + line.full.len());
    }
    let line_of = |offset: usize| starts.partition_point(|s| *s <= offset).saturating_sub(1);
    let mut matched = std::collections::BTreeSet::new();
    for found in regex.find_iter(text) {
        check_deadline(deadline)?;
        let found = found.map_err(|_| timeout_message())?;
        let first = line_of(found.start());
        let last = line_of(found.start().max(found.end().saturating_sub(1)));
        matched.extend(first..=last);
    }
    Ok(matched.into_iter().collect())
}

fn timeout_message() -> String {
    format!(
        "grep_files scan timed out after {}s — pattern may be too complex or directory too large",
        SCAN_TIMEOUT.as_secs()
    )
}

/// The clock is read once per 4096 lines, not on every line.
fn deadline_due(line: usize) -> bool {
    line.is_multiple_of(4096)
}

fn check_deadline(deadline: Instant) -> Result<(), String> {
    if Instant::now() >= deadline {
        Err(timeout_message())
    } else {
        Ok(())
    }
}

struct Scan<'a> {
    sandbox: &'a Sandbox,
    regex: &'a Regex,
    rules: &'a Rules,
    root: &'a Path,
    include: &'a str,
    globs: Option<&'static [&'static str]>,
    mode: Mode,
    multiline: bool,
    context: i64,
    stop_after: i64,
    deadline: Instant,
    match_count: i64,
    hits: Hits,
}

impl Scan<'_> {
    /// `os.walk` top-down: one directory's files, then each subdirectory.
    /// `Break` means the scan stopped early.
    fn walk(&mut self, current: &Path) -> Result<bool, String> {
        let mut dirs: Vec<(String, PathBuf)> = Vec::new();
        let mut files: Vec<(String, PathBuf)> = Vec::new();
        for (name, path) in children(current) {
            if is_dir(&path) {
                dirs.push((name, path));
            } else {
                files.push((name, path));
            }
        }
        dirs.retain(|(name, path)| {
            !name.starts_with('.')
                && !is_skipped_dir(name)
                && !self
                    .rules
                    .is_ignored(&crate::glob::rel_posix(path, self.root), true)
        });
        dirs.sort_by(|a, b| a.0.cmp(&b.0));
        files.sort_by(|a, b| a.0.cmp(&b.0));

        for (name, path) in files {
            if name.starts_with('.') || !fnmatch(&name, self.include) {
                continue;
            }
            if let Some(globs) = self.globs {
                if !globs.iter().any(|glob| fnmatch(&name, glob)) {
                    continue;
                }
            }
            let rel = crate::glob::rel_posix(&path, self.root);
            if self.rules.is_ignored(&rel, false) {
                continue;
            }
            if !self.readable(&path) {
                continue;
            }
            check_deadline(self.deadline)?;
            if !self.scan_file(&path)? {
                return Ok(false);
            }
        }
        for (_, path) in dirs {
            if is_symlink(&path) || !self.sandbox.permits_link(&path) {
                continue;
            }
            if !self.walk(&path)? {
                return Ok(false);
            }
        }
        Ok(true)
    }

    /// Only regular files are opened: a FIFO, socket or device would block the
    /// scan (or never end), and `metadata` follows links to judge it.
    fn readable(&self, path: &Path) -> bool {
        is_file(path) && self.sandbox.permits_link(path)
    }

    /// `false` once `stop_after` matching lines have been seen.
    fn scan_file(&mut self, path: &Path) -> Result<bool, String> {
        // Open the resolved file through the sandbox, so a folder swapped for
        // a link after `readable` cannot redirect the read.
        let Some(real) = resolve(path) else {
            return Ok(true);
        };
        let Ok(raw) = self
            .sandbox
            .open_confined(&real)
            .and_then(|file| read_capped(file, MAX_FILE_BYTES + 1))
        else {
            return Ok(true);
        };
        if raw.len() > MAX_FILE_BYTES {
            return Ok(true);
        }
        let Ok(text) = String::from_utf8(raw) else {
            return Ok(true);
        };
        // `read_text` translates newlines before `splitlines` runs.
        let text = text.replace("\r\n", "\n").replace('\r', "\n");
        let lines = splitlines(&text);
        let matched =
            matched_line_indexes(self.regex, &text, &lines, self.multiline, self.deadline)?;
        if matched.is_empty() {
            return Ok(true);
        }
        if self.mode != Mode::Content {
            self.hits.files.push((path.to_path_buf(), matched.len()));
            return Ok(true);
        }
        let display = self.sandbox.display_path(path);
        let last_line = i64::try_from(lines.len()).unwrap_or(i64::MAX) - 1;
        // Merge overlapping +-context ranges into blocks.
        let mut blocks: Vec<(i64, i64)> = Vec::new();
        for &i in &matched {
            let i = i64::try_from(i).unwrap_or(i64::MAX);
            let lo = (i - self.context).max(0);
            let hi = last_line.min(i + self.context);
            match blocks.last_mut() {
                Some(block) if lo <= block.1 + 1 => block.1 = hi,
                _ => blocks.push((lo, hi)),
            }
        }
        for (lo, hi) in blocks {
            if self.context > 0 && matches!(self.hits.entries.last(), Some(Some(_))) {
                self.hits.entries.push(None);
            }
            for j in lo..=hi {
                let index = usize::try_from(j).unwrap_or(usize::MAX);
                let is_match = matched.binary_search(&index).is_ok();
                let body = lines.get(index).map_or("", |line| line.body);
                self.hits.entries.push(Some((
                    is_match,
                    display.clone(),
                    index + 1,
                    body.to_owned(),
                )));
                if is_match {
                    self.match_count += 1;
                    if self.match_count >= self.stop_after {
                        self.hits.complete = false;
                        return Ok(false);
                    }
                }
            }
        }
        Ok(true)
    }
}

fn format_line(display: &str, lineno: usize, content: &str, is_match: bool) -> String {
    let content = char_prefix(content, MAX_LINE_CHARS);
    if is_match {
        format!("{display}:{lineno}: {content}")
    } else {
        format!("{display}-{lineno}- {content}")
    }
}

/// Tell the model a page is partial and how to get the rest.
fn page_notice(noun: &str, offset: i64, shown: i64, total: Option<i64>) -> String {
    let span = format!("{noun} {}-{}", offset + 1, offset + shown);
    match total {
        None => format!(
            "[Showing {span}; more exist. Pass offset={} for the next page, or narrow directory/include/type.]",
            offset + shown
        ),
        Some(total) if offset + shown < total => format!(
            "[Showing {span} of {total}. Pass offset={} for the next page, or narrow directory/include/type.]",
            offset + shown
        ),
        Some(total) => format!("[Showing {span} of {total}.]"),
    }
}

fn is_context(entry: Option<&Entry>) -> bool {
    matches!(entry, Some(Some((false, ..))))
}

fn render_content(hits: &Hits, offset: i64, limit: i64) -> Vec<String> {
    let entries = &hits.entries;
    let positions: Vec<usize> = entries
        .iter()
        .enumerate()
        .filter(|(_, e)| matches!(e, Some((true, ..))))
        .map(|(i, _)| i)
        .collect();
    let total = i64::try_from(positions.len()).unwrap_or(i64::MAX);
    if offset >= total {
        return vec![format!(
            "No entries at offset {offset} — only {total} matching lines."
        )];
    }
    let more = total > offset + limit || !hits.complete;
    let window: &[Entry] = if offset == 0 && !more {
        entries
    } else {
        // Keep the context lines around the page's matches, but stop at the
        // next match or block separator so no off-page match slips in.
        let first = usize::try_from(offset).unwrap_or(0);
        let last = usize::try_from((offset + limit).min(total) - 1).unwrap_or(0);
        let mut start = positions.get(first).copied().unwrap_or(0);
        let mut end = positions.get(last).copied().unwrap_or(0);
        while start > 0 && is_context(entries.get(start - 1)) {
            start -= 1;
        }
        while is_context(entries.get(end + 1)) {
            end += 1;
        }
        entries.get(start..=end).unwrap_or_default()
    };
    let mut lines: Vec<String> = Vec::new();
    for entry in window {
        match entry {
            None => {
                if lines.last().is_some_and(|last| last != "--") {
                    lines.push("--".to_owned());
                }
            }
            Some((is_match, display, lineno, text)) => {
                lines.push(format_line(display, *lineno, text, *is_match));
            }
        }
    }
    while lines.last().is_some_and(|last| last == "--") {
        lines.pop();
    }
    let shown = (offset + limit).min(total) - offset;
    if more {
        lines.push(page_notice("matching lines", offset, shown, None));
    } else if offset > 0 {
        lines.push(page_notice("matching lines", offset, shown, Some(total)));
    }
    lines
}

fn path_key(path: &Path) -> Vec<String> {
    path.components()
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect()
}

fn render_files(
    hits: &Hits,
    mode: Mode,
    offset: i64,
    limit: i64,
    sandbox: &Sandbox,
) -> Vec<String> {
    let mut files: Vec<(&PathBuf, usize)> = hits.files.iter().map(|(p, c)| (p, *c)).collect();
    if mode == Mode::FilesWithMatches {
        // Recently edited files are usually the ones the task is about.
        let mut keyed: Vec<(i128, Vec<String>, &PathBuf, usize)> = files
            .iter()
            .map(|(p, c)| (mtime_ns(p), path_key(p), *p, *c))
            .collect();
        keyed.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
        files = keyed.into_iter().map(|(_, _, p, c)| (p, c)).collect();
    } else {
        files.sort_by_key(|(p, _)| path_key(p));
    }
    let total = i64::try_from(files.len()).unwrap_or(i64::MAX);
    if offset >= total {
        return vec![format!(
            "No entries at offset {offset} — only {total} files."
        )];
    }
    let start = usize::try_from(offset).unwrap_or(0);
    let take = usize::try_from(limit).unwrap_or(usize::MAX);
    let page: Vec<&(&PathBuf, usize)> = files.iter().skip(start).take(take).collect();
    let shown = i64::try_from(page.len()).unwrap_or(i64::MAX);
    let mut lines: Vec<String> = page
        .iter()
        .map(|(path, count)| {
            if mode == Mode::FilesWithMatches {
                sandbox.display_path(path)
            } else {
                format!("{}:{count}", sandbox.display_path(path))
            }
        })
        .collect();
    let partial = offset > 0 || total > offset + limit;
    if mode == Mode::Count {
        let matching: usize = files.iter().map(|(_, count)| count).sum();
        let mut summary = format!("[{matching} matching lines in {total} files");
        if partial {
            summary.push_str(&format!(
                "; showing files {}-{}",
                offset + 1,
                offset + shown
            ));
            if offset + shown < total {
                summary.push_str(&format!(
                    ". Pass offset={} for the next page",
                    offset + shown
                ));
            }
        }
        lines.push(format!("{summary}.]"));
    } else if partial {
        lines.push(page_notice("files", offset, shown, Some(total)));
    }
    lines
}

pub(crate) fn run(sandbox: &Sandbox, query: &Query<'_>) -> Result<String, String> {
    let resolved = search_root::validate(sandbox, query.directory, "grep")?;

    let pattern_chars = query.pattern.chars().count();
    if pattern_chars > MAX_PATTERN_LEN {
        return Err(format!(
            "Pattern too long ({pattern_chars} chars, max {MAX_PATTERN_LEN})"
        ));
    }
    let mode = match query.output_mode {
        "content" => Mode::Content,
        "files_with_matches" => Mode::FilesWithMatches,
        "count" => Mode::Count,
        _ => {
            return Err("output_mode must be 'content', 'files_with_matches' or 'count'".to_owned())
        }
    };
    let file_type = crate::pyfmt::strip(query.file_type);
    if !file_type.is_empty() && !valid_type_name(file_type) {
        return Err(format!(
            "Invalid type '{}'. Use a ripgrep type name such as 'py'.",
            query.file_type
        ));
    }

    if !query.multiline {
        let crosses_lines = if query.fixed_strings {
            query.pattern.contains(['\n', '\r'])
        } else {
            contains_line_break_expression(query.pattern)
        };
        if crosses_lines {
            return Err(
                "grep is line-oriented and cannot match newline expressions. \
                        Pass multiline=true, search each line pattern separately, or \
                        use a scoped source search query for cross-line relationships."
                    .to_owned(),
            );
        }
    }

    let mut flags = String::new();
    if query.case_insensitive {
        flags.push('i');
    }
    if query.multiline {
        flags.push_str("ms");
    }
    let source = if query.fixed_strings {
        fancy_regex::escape(query.pattern).into_owned()
    } else {
        query.pattern.to_owned()
    };
    let regex = Regex::new(&if flags.is_empty() {
        source
    } else {
        format!("(?{flags}){source}")
    })
    .map_err(|e| format!("Invalid regex: {e}"))?;

    let limit = query.max_results.clamp(1, MAX_PAGE);
    let offset = query.offset.max(0);
    let context = query.context.clamp(0, MAX_CONTEXT);
    let include = if query.include.is_empty() {
        "*"
    } else {
        query.include
    };

    let globs = type_globs(file_type)?;
    let rules = Rules::load(&resolved);
    let mut scan = Scan {
        sandbox,
        regex: &regex,
        rules: &rules,
        root: &resolved,
        include,
        globs,
        mode,
        multiline: query.multiline,
        context,
        stop_after: offset.saturating_add(limit).saturating_add(1),
        deadline: Instant::now() + SCAN_TIMEOUT,
        match_count: 0,
        hits: Hits {
            entries: Vec::new(),
            files: Vec::new(),
            complete: true,
        },
    };
    scan.walk(&resolved)?;
    let hits = scan.hits;

    if hits.entries.is_empty() && hits.files.is_empty() {
        let mut scope = format!("include={include}");
        if !file_type.is_empty() {
            scope.push_str(&format!(", type={file_type}"));
        }
        return Ok(format!(
            "No matches for pattern '{}' in {} ({scope})",
            query.pattern,
            sandbox.display_path(&resolved)
        ));
    }
    let lines = if mode == Mode::Content {
        render_content(&hits, offset, limit)
    } else {
        render_files(&hits, mode, offset, limit, sandbox)
    };
    Ok(lines.join("\n"))
}

#[async_trait]
impl Tool for GrepTool {
    fn name(&self) -> &str {
        "grep"
    }

    fn spec(&self) -> Value {
        definition(
            "grep",
            DESCRIPTION,
            json!({
                "pattern": property(None, "Regex to match per line (e.g. 'def main', 'TODO|FIXME').", &[("type", json!("string"))]),
                "directory": property(Some(json!(".")), "Search root (default '.' = workspace root).", &[("type", json!("string"))]),
                "include": property(Some(json!("*")), "Filename glob to filter files (e.g. '*.py'). Default '*'.", &[("type", json!("string"))]),
                "type": property(Some(json!("")), "File type to search, as a ripgrep type name (e.g. 'py', 'ts', 'rust'). Faster and broader than include for a language.", &[("type", json!("string"))]),
                "output_mode": property(Some(json!("content")), "'content' (default): matching lines as 'file:line: text'. 'files_with_matches': only file paths, newest first — the cheapest way to locate code. 'count': matching lines per file plus a total.", &[("enum", json!(MODES)), ("type", json!("string"))]),
                "max_results": property(Some(json!(100)), "Maximum entries per page: matching lines, files or per-file counts depending on output_mode (default 100, max 1000).", &[("type", json!("integer"))]),
                "offset": property(Some(json!(0)), "Skip this many entries first. Use the offset a truncation notice gives to fetch the next page.", &[("type", json!("integer"))]),
                "case_insensitive": property(Some(json!(false)), "Case-insensitive matching (default false).", &[("type", json!("boolean"))]),
                "fixed_strings": property(Some(json!(false)), "Treat pattern as a literal string, not a regex.", &[("type", json!("boolean"))]),
                "multiline": property(Some(json!(false)), "Let the pattern span lines; '.' also matches newlines. Write \\r?\\n to also match Windows line endings (default false).", &[("type", json!("boolean"))]),
                "context": property(Some(json!(0)), "Lines of context to show around each match in content mode, like grep -C (default 0, max 10). Context lines use 'file-line-' prefixes.", &[("type", json!("integer"))]),
            }),
            &["pattern"],
        )
    }

    async fn call(&self, args: Value, ctx: &ToolCtx) -> ToolOutput {
        let parsed = match args::parse("grep", &fields(), &args) {
            Ok(parsed) => parsed,
            Err(message) => return ToolOutput::error(&message),
        };
        let root = ctx.workspace_root.clone();
        run_blocking("grep", move || {
            let query = Query {
                pattern: &parsed.str("pattern"),
                directory: &parsed.str("directory"),
                include: &parsed.str("include"),
                file_type: &parsed.str("type"),
                output_mode: &parsed.str("output_mode"),
                max_results: parsed.int("max_results"),
                offset: parsed.int("offset"),
                case_insensitive: parsed.flag("case_insensitive"),
                fixed_strings: parsed.flag("fixed_strings"),
                multiline: parsed.flag("multiline"),
                context: parsed.int("context"),
            };
            run(&Sandbox::new(&root), &query)
        })
        .await
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    use crate::testutil::{link_dir, link_file, set_mtime, workspace};

    fn query<'a>(pattern: &'a str) -> Query<'a> {
        Query {
            pattern,
            directory: ".",
            include: "*",
            file_type: "",
            output_mode: "content",
            max_results: 100,
            offset: 0,
            case_insensitive: false,
            fixed_strings: false,
            multiline: false,
            context: 0,
        }
    }

    fn grep(sandbox: &Sandbox, query: &Query<'_>) -> String {
        run(sandbox, query).unwrap()
    }

    fn match_entry(display: &str, line: usize, text: &str) -> Entry {
        Some((true, display.to_owned(), line, text.to_owned()))
    }

    fn context_entry(display: &str, line: usize, text: &str) -> Entry {
        Some((false, display.to_owned(), line, text.to_owned()))
    }

    fn hits(entries: Vec<Entry>, complete: bool) -> Hits {
        Hits {
            entries,
            files: Vec::new(),
            complete,
        }
    }

    #[test]
    fn line_break_expressions_are_detected() {
        for pattern in [
            "a\nb", "a\rb", r"a\nb", r"a\rb", r"\n", r"x\\\nz", r"\\\\\r",
        ] {
            assert!(contains_line_break_expression(pattern), "{pattern:?}");
        }
        for pattern in [r"a\\nb", r"a\\\\rb", "plain", r"\d+", r"a\", "", r"\\"] {
            assert!(!contains_line_break_expression(pattern), "{pattern:?}");
        }
    }

    #[test]
    fn type_names_are_one_to_thirty_two_safe_characters() {
        for name in ["py", "c++", "a-b_c", "X9", &"a".repeat(32)] {
            assert!(valid_type_name(name), "{name}");
        }
        for name in ["", "py!", "a b", &"a".repeat(33), "é", "a/b"] {
            assert!(!valid_type_name(name), "{name}");
        }
    }

    #[test]
    fn type_globs_resolve_case_insensitively_and_list_the_known_names() {
        assert_eq!(type_globs("").unwrap(), None);
        assert_eq!(type_globs("PY").unwrap(), Some(&["*.py", "*.pyi"][..]));
        assert_eq!(type_globs("rust").unwrap(), Some(&["*.rs"][..]));
        let err = type_globs("zig").unwrap_err();
        assert!(err.starts_with("Unknown type 'zig'. Use one of c, cpp, cs, css, go, html,"));
        assert!(err.ends_with("toml, ts, yaml, or filter with include."));
        assert_eq!(TYPE_GLOBS.len(), 22);
        let names: Vec<&str> = TYPE_GLOBS.iter().map(|(n, _)| *n).collect();
        let mut sorted = names.clone();
        sorted.sort_unstable();
        assert_eq!(names, sorted, "the error text lists the names sorted");
    }

    #[test]
    fn lines_are_cut_at_two_hundred_characters() {
        let long = "é".repeat(250);
        let line = format_line("f.rs", 7, &long, true);
        assert_eq!(line, format!("f.rs:7: {}", "é".repeat(200)));
        assert_eq!(format_line("f.rs", 7, "short", true), "f.rs:7: short");
        assert_eq!(format_line("f.rs", 8, "ctx", false), "f.rs-8- ctx");
        assert_eq!(
            format_line("f.rs", 8, &"x".repeat(201), false),
            format!("f.rs-8- {}", "x".repeat(200))
        );
    }

    #[test]
    fn page_notices_have_three_shapes() {
        assert_eq!(
            page_notice("files", 0, 5, None),
            "[Showing files 1-5; more exist. Pass offset=5 for the next page, or narrow directory/include/type.]"
        );
        assert_eq!(
            page_notice("files", 5, 5, Some(20)),
            "[Showing files 6-10 of 20. Pass offset=10 for the next page, or narrow directory/include/type.]"
        );
        assert_eq!(
            page_notice("matching lines", 10, 3, Some(13)),
            "[Showing matching lines 11-13 of 13.]"
        );
        assert_eq!(
            page_notice("files", 0, 5, Some(5)),
            "[Showing files 1-5 of 5.]"
        );
    }

    fn sample() -> Vec<Entry> {
        vec![
            context_entry("a", 1, "c1"),
            match_entry("a", 2, "m1"),
            context_entry("a", 3, "c2"),
            None,
            context_entry("a", 9, "c3"),
            match_entry("a", 10, "m2"),
            context_entry("a", 11, "c4"),
            None,
            match_entry("b", 1, "m3"),
        ]
    }

    #[test]
    fn render_content_whole_result_keeps_separators() {
        let out = render_content(&hits(sample(), true), 0, 100);
        assert_eq!(
            out,
            vec![
                "a-1- c1", "a:2: m1", "a-3- c2", "--", "a-9- c3", "a:10: m2", "a-11- c4", "--",
                "b:1: m3"
            ]
        );
    }

    #[test]
    fn render_content_pages_keep_context_but_not_neighbours_matches() {
        let h = hits(sample(), true);
        assert_eq!(
            render_content(&h, 0, 1),
            vec![
                "a-1- c1",
                "a:2: m1",
                "a-3- c2",
                "[Showing matching lines 1-1; more exist. Pass offset=1 for the next page, or narrow directory/include/type.]"
            ]
        );
        assert_eq!(
            render_content(&h, 1, 1),
            vec![
                "a-9- c3",
                "a:10: m2",
                "a-11- c4",
                "[Showing matching lines 2-2; more exist. Pass offset=2 for the next page, or narrow directory/include/type.]"
            ]
        );
        assert_eq!(
            render_content(&h, 2, 5),
            vec!["b:1: m3", "[Showing matching lines 3-3 of 3.]"]
        );
    }

    #[test]
    fn render_content_past_the_end_and_incomplete() {
        let h = hits(sample(), true);
        assert_eq!(
            render_content(&h, 3, 5),
            vec!["No entries at offset 3 — only 3 matching lines."]
        );
        let cut = hits(vec![match_entry("a", 1, "x")], false);
        assert_eq!(
            render_content(&cut, 0, 5),
            vec![
                "a:1: x",
                "[Showing matching lines 1-1; more exist. Pass offset=1 for the next page, or narrow directory/include/type.]"
            ]
        );
    }

    #[test]
    fn render_content_trims_a_trailing_separator() {
        let h = hits(
            vec![match_entry("a", 1, "x"), None, context_entry("a", 5, "y")],
            true,
        );
        assert_eq!(render_content(&h, 0, 5), vec!["a:1: x", "--", "a-5- y"]);
        let h = hits(vec![match_entry("a", 1, "x"), None], true);
        assert_eq!(render_content(&h, 0, 5), vec!["a:1: x"]);
        let h = hits(vec![None, None, match_entry("a", 1, "x")], true);
        assert_eq!(render_content(&h, 0, 5), vec!["a:1: x"]);
    }

    fn file_hits() -> Hits {
        Hits {
            entries: Vec::new(),
            files: vec![
                (PathBuf::from("/w/b.txt"), 3),
                (PathBuf::from("/w/a.txt"), 1),
                (PathBuf::from("/w/c.txt"), 5),
            ],
            complete: true,
        }
    }

    #[test]
    fn render_files_count_mode_is_path_sorted_with_a_total() {
        let (_d, s) = workspace(&[]);
        let out = render_files(&file_hits(), Mode::Count, 0, 10, &s);
        assert_eq!(out.len(), 4);
        assert!(
            out[0].ends_with("a.txt:1")
                && out[1].ends_with("b.txt:3")
                && out[2].ends_with("c.txt:5")
        );
        assert_eq!(out[3], "[9 matching lines in 3 files.]");
    }

    #[test]
    fn render_files_count_mode_pages() {
        let (_d, s) = workspace(&[]);
        let out = render_files(&file_hits(), Mode::Count, 0, 2, &s);
        assert_eq!(
            out.last().unwrap(),
            "[9 matching lines in 3 files; showing files 1-2. Pass offset=2 for the next page.]"
        );
        let out = render_files(&file_hits(), Mode::Count, 2, 2, &s);
        assert_eq!(out.len(), 2);
        assert_eq!(
            out.last().unwrap(),
            "[9 matching lines in 3 files; showing files 3-3.]"
        );
        let out = render_files(&file_hits(), Mode::Count, 3, 2, &s);
        assert_eq!(out, vec!["No entries at offset 3 — only 3 files."]);
    }

    #[test]
    fn render_files_list_mode_sorts_by_time_then_path() {
        let (d, s) = workspace(&[("a.txt", ""), ("b.txt", ""), ("c.txt", "")]);
        set_mtime(&d.path().join("a.txt"), 100);
        set_mtime(&d.path().join("b.txt"), 300);
        set_mtime(&d.path().join("c.txt"), 300);
        let root = s.root().to_path_buf();
        let h = Hits {
            entries: Vec::new(),
            files: ["a.txt", "c.txt", "b.txt"]
                .iter()
                .map(|n| (root.join(n), 1))
                .collect(),
            complete: true,
        };
        assert_eq!(
            render_files(&h, Mode::FilesWithMatches, 0, 10, &s),
            vec!["b.txt", "c.txt", "a.txt"]
        );
        assert_eq!(
            render_files(&h, Mode::FilesWithMatches, 0, 2, &s),
            vec![
                "b.txt",
                "c.txt",
                "[Showing files 1-2 of 3. Pass offset=2 for the next page, or narrow directory/include/type.]"
            ]
        );
        assert_eq!(
            render_files(&h, Mode::FilesWithMatches, 2, 2, &s),
            vec!["a.txt", "[Showing files 3-3 of 3.]"]
        );
    }

    #[test]
    fn multiline_matches_mark_every_spanned_line() {
        let text = "a\nb\nc\nd";
        let lines = splitlines(text);
        let regex = Regex::new("(?ms)b.*c").unwrap();
        let far = Instant::now() + Duration::from_secs(60);
        assert_eq!(
            matched_line_indexes(&regex, text, &lines, true, far).unwrap(),
            vec![1, 2]
        );
        let regex = Regex::new("(?ms)^d").unwrap();
        assert_eq!(
            matched_line_indexes(&regex, text, &lines, true, far).unwrap(),
            vec![3]
        );
        let regex = Regex::new("(?ms)a\nb\nc\nd").unwrap();
        assert_eq!(
            matched_line_indexes(&regex, text, &lines, true, far).unwrap(),
            vec![0, 1, 2, 3]
        );
        let regex = Regex::new("(?ms)x*").unwrap();
        assert_eq!(
            matched_line_indexes(&regex, "", &[], true, far).unwrap(),
            vec![0],
            "an empty match in an empty file reports line 0, like Python"
        );
    }

    #[test]
    fn limits_have_their_documented_values() {
        assert_eq!(MAX_FILE_BYTES, 67_108_864);
        assert_eq!(MAX_PATTERN_LEN, 500);
        assert_eq!(MAX_LINE_CHARS, 200);
        assert_eq!(MAX_CONTEXT, 10);
        assert_eq!(MAX_PAGE, 1000);
        assert_eq!(SCAN_TIMEOUT, Duration::from_secs(10));
    }

    #[test]
    fn the_clock_is_read_every_4096_lines() {
        assert!(deadline_due(0) && deadline_due(4096) && deadline_due(8192));
        assert!(!deadline_due(1) && !deadline_due(4095) && !deadline_due(4097));
    }

    #[test]
    fn an_expired_deadline_is_a_timeout() {
        let text = "a";
        let lines = splitlines(text);
        let past = Instant::now() - Duration::from_secs(1);
        let regex = Regex::new("a").unwrap();
        let expected = "grep_files scan timed out after 10s — pattern may be too complex or directory too large";
        assert_eq!(
            matched_line_indexes(&regex, text, &lines, false, past).unwrap_err(),
            expected
        );
        let regex = Regex::new("(?ms)a").unwrap();
        assert_eq!(
            matched_line_indexes(&regex, text, &lines, true, past).unwrap_err(),
            expected
        );
        assert!(check_deadline(Instant::now() + Duration::from_secs(60)).is_ok());
        assert_eq!(check_deadline(past).unwrap_err(), expected);
    }

    #[test]
    fn only_regular_files_are_readable() {
        let (_d, s) = workspace(&[
            (
                "a.txt", "x
",
            ),
            (
                "dir/b.txt",
                "y
",
            ),
        ]);
        let regex = Regex::new("x").unwrap();
        let rules = Rules::empty();
        let scan = Scan {
            sandbox: &s,
            regex: &regex,
            rules: &rules,
            root: s.root(),
            include: "*",
            globs: None,
            mode: Mode::Content,
            multiline: false,
            context: 0,
            stop_after: 100,
            deadline: Instant::now(),
            match_count: 0,
            hits: hits(Vec::new(), true),
        };
        assert!(scan.readable(&s.root().join("a.txt")));
        assert!(
            !scan.readable(&s.root().join("dir")),
            "a folder is not a file"
        );
        assert!(!scan.readable(&s.root().join("missing.txt")));
    }

    #[test]
    fn the_walk_stops_at_an_expired_deadline() {
        let (_d, s) = workspace(&[("a.txt", "needle\n")]);
        let regex = Regex::new("needle").unwrap();
        let rules = Rules::empty();
        let mut scan = Scan {
            sandbox: &s,
            regex: &regex,
            rules: &rules,
            root: s.root(),
            include: "*",
            globs: None,
            mode: Mode::Content,
            multiline: false,
            context: 0,
            stop_after: 100,
            deadline: Instant::now() - Duration::from_secs(1),
            match_count: 0,
            hits: hits(Vec::new(), true),
        };
        assert!(scan
            .walk(s.root())
            .unwrap_err()
            .contains("timed out after 10s"));
    }

    #[test]
    fn the_walk_reports_an_early_stop_and_keeps_only_what_it_needs() {
        let (_d, s) = workspace(&[("a.txt", "x\nx\nx\nx\n"), ("b.txt", "x\n")]);
        let regex = Regex::new("x").unwrap();
        let rules = Rules::empty();
        let mut scan = Scan {
            sandbox: &s,
            regex: &regex,
            rules: &rules,
            root: s.root(),
            include: "*",
            globs: None,
            mode: Mode::Content,
            multiline: false,
            context: 0,
            stop_after: 3,
            deadline: Instant::now() + Duration::from_secs(60),
            match_count: 0,
            hits: hits(Vec::new(), true),
        };
        assert!(!scan.walk(s.root()).unwrap(), "the walk stopped early");
        assert!(!scan.hits.complete);
        assert_eq!(scan.match_count, 3);
        assert_eq!(scan.hits.entries.len(), 3, "b.txt was never opened");
    }

    #[test]
    fn the_scan_stops_once_enough_matching_lines_are_seen() {
        let (_d, s) = workspace(&[("a.txt", "x\nx\nx\nx\n")]);
        let out = grep(
            &s,
            &Query {
                max_results: 2,
                ..query("x")
            },
        );
        assert_eq!(
            out,
            "a.txt:1: x\na.txt:2: x\n[Showing matching lines 1-2; more exist. Pass offset=2 for the next page, or narrow directory/include/type.]"
        );
    }

    #[test]
    fn context_blocks_merge_and_separate() {
        let (_d, s) = workspace(&[("a.txt", "1\nHIT\n3\n4\n5\n6\nHIT\n8\n")]);
        let out = grep(
            &s,
            &Query {
                context: 1,
                ..query("HIT")
            },
        );
        assert_eq!(
            out,
            "a.txt-1- 1\na.txt:2: HIT\na.txt-3- 3\n--\na.txt-6- 6\na.txt:7: HIT\na.txt-8- 8"
        );
        let out = grep(
            &s,
            &Query {
                context: 2,
                ..query("HIT")
            },
        );
        assert_eq!(
            out,
            "a.txt-1- 1\na.txt:2: HIT\na.txt-3- 3\na.txt-4- 4\na.txt-5- 5\na.txt-6- 6\na.txt:7: HIT\na.txt-8- 8"
        );
    }

    #[test]
    fn a_file_over_the_size_cap_is_skipped() {
        let (d, s) = workspace(&[("small.txt", "needle\n")]);
        let big = d.path().join("big.txt");
        let mut content = b"needle\n".to_vec();
        content.resize(MAX_FILE_BYTES + 1, b'.');
        std::fs::write(&big, content).unwrap();
        assert_eq!(
            grep(
                &s,
                &Query {
                    output_mode: "files_with_matches",
                    ..query("needle")
                }
            ),
            "small.txt"
        );
        let mut exact = b"needle\n".to_vec();
        exact.resize(MAX_FILE_BYTES, b'.');
        std::fs::write(&big, exact).unwrap();
        let out = grep(
            &s,
            &Query {
                output_mode: "files_with_matches",
                ..query("needle")
            },
        );
        assert_eq!(
            out.lines().count(),
            2,
            "a file of exactly the cap is read: {out}"
        );
    }

    #[test]
    fn invalid_utf8_files_are_skipped() {
        let (d, s) = workspace(&[("ok.txt", "needle\n")]);
        std::fs::write(d.path().join("bad.txt"), b"needle \xff\n").unwrap();
        assert_eq!(grep(&s, &query("needle")), "ok.txt:1: needle");
    }

    #[test]
    fn validation_errors_keep_the_python_wording() {
        let (_d, s) = workspace(&[("a.txt", "x\n")]);
        let err = |q: Query<'_>| run(&s, &q).unwrap_err();
        assert_eq!(
            err(query(&"a".repeat(501))),
            "Pattern too long (501 chars, max 500)"
        );
        assert!(
            run(&s, &query(&"é".repeat(500))).is_ok(),
            "length counts characters"
        );
        assert_eq!(
            err(Query {
                output_mode: "bogus",
                ..query("x")
            }),
            "output_mode must be 'content', 'files_with_matches' or 'count'"
        );
        assert_eq!(
            err(Query {
                file_type: "p y",
                ..query("x")
            }),
            "Invalid type 'p y'. Use a ripgrep type name such as 'py'."
        );
        assert_eq!(
            err(Query {
                file_type: " p y ",
                ..query("x")
            }),
            "Invalid type ' p y '. Use a ripgrep type name such as 'py'."
        );
        assert!(err(query("a\nb"))
            .starts_with("grep is line-oriented and cannot match newline expressions."));
        assert!(err(Query {
            fixed_strings: true,
            ..query("a\nb")
        })
        .starts_with("grep is line-oriented"));
        assert!(run(
            &s,
            &Query {
                fixed_strings: true,
                ..query(r"a\nb")
            }
        )
        .is_ok());
        assert!(run(
            &s,
            &Query {
                multiline: true,
                ..query("a\nb")
            }
        )
        .is_ok());
        assert!(err(query("(")).starts_with("Invalid regex: "));
        assert_eq!(
            err(Query {
                file_type: "zig",
                ..query("x")
            })
            .split('.')
            .next()
            .unwrap(),
            "Unknown type 'zig'"
        );
    }

    #[test]
    fn regex_flags_apply() {
        let (_d, s) = workspace(&[("a.txt", "Needle\nNEEDLE\nneedle\n")]);
        assert_eq!(grep(&s, &query("needle")), "a.txt:3: needle");
        let out = grep(
            &s,
            &Query {
                case_insensitive: true,
                ..query("needle")
            },
        );
        assert_eq!(out.lines().count(), 3);
        // "n.e" as a literal matches nothing; as a regex it would match every line.
        assert_eq!(
            grep(
                &s,
                &Query {
                    fixed_strings: true,
                    ..query("n.e")
                }
            ),
            format!(
                "No matches for pattern 'n.e' in {} (include=*)",
                s.root().display()
            )
        );
        assert_eq!(grep(&s, &query("n.e")).lines().count(), 1);
    }

    #[test]
    fn extreme_offsets_do_not_overflow() {
        let (_d, s) = workspace(&[("a.txt", "x\nx\n")]);
        let out = grep(
            &s,
            &Query {
                offset: i64::MAX,
                ..query("x")
            },
        );
        assert_eq!(
            out,
            "No entries at offset 9223372036854775807 — only 2 matching lines."
        );
        let out = grep(
            &s,
            &Query {
                offset: i64::MAX,
                output_mode: "count",
                ..query("x")
            },
        );
        assert_eq!(
            out,
            "No entries at offset 9223372036854775807 — only 1 files."
        );
        let out = grep(
            &s,
            &Query {
                max_results: i64::MAX,
                offset: i64::MIN,
                ..query("x")
            },
        );
        assert_eq!(out.lines().count(), 2);
    }

    #[test]
    fn page_limits_are_clamped() {
        let (_d, s) = workspace(&[("a.txt", "x\nx\nx\n")]);
        let out = grep(
            &s,
            &Query {
                max_results: 0,
                ..query("x")
            },
        );
        assert_eq!(out.lines().count(), 2, "limit 0 acts as 1: {out}");
        let out = grep(
            &s,
            &Query {
                offset: -5,
                ..query("x")
            },
        );
        assert_eq!(out.lines().count(), 3);
        let out = grep(
            &s,
            &Query {
                max_results: 50_000,
                ..query("x")
            },
        );
        assert_eq!(out.lines().count(), 3);
        let out = grep(
            &s,
            &Query {
                context: 99,
                ..query("x")
            },
        );
        assert_eq!(out.lines().count(), 3);
    }

    #[test]
    fn no_match_message_lists_the_scope() {
        let (_d, s) = workspace(&[("a.py", "x\n")]);
        assert_eq!(
            grep(
                &s,
                &Query {
                    include: "*.py",
                    file_type: " py ",
                    ..query("zzz")
                }
            ),
            format!(
                "No matches for pattern 'zzz' in {} (include=*.py, type=py)",
                s.root().display()
            )
        );
        assert_eq!(
            grep(
                &s,
                &Query {
                    include: "",
                    ..query("zzz")
                }
            ),
            format!(
                "No matches for pattern 'zzz' in {} (include=*)",
                s.root().display()
            )
        );
    }

    #[test]
    fn gitignore_and_generated_directories_are_skipped() {
        let (_d, s) = workspace(&[
            (".gitignore", "*.log\nskip_dir/\n"),
            ("a.txt", "needle\n"),
            ("a.log", "needle\n"),
            ("skip_dir/b.txt", "needle\n"),
            ("node_modules/c.txt", "needle\n"),
            (".hidden/d.txt", "needle\n"),
            (".e.txt", "needle\n"),
            ("sub/f.txt", "needle\n"),
        ]);
        assert_eq!(
            grep(
                &s,
                &Query {
                    output_mode: "count",
                    ..query("needle")
                }
            ),
            format!(
                "{}\n{}\n[2 matching lines in 2 files.]",
                "a.txt:1", "sub/f.txt:1"
            )
        );
    }

    #[test]
    fn a_link_leading_out_of_the_workspace_is_not_searched() {
        let (d, _s) = workspace(&[
            ("ws/in.txt", "needle in\n"),
            ("outside/secret.txt", "needle out\n"),
        ]);
        let ws = d.path().join("ws");
        let sandbox = Sandbox::new(&ws);
        link_dir(&d.path().join("outside"), &ws.join("escape"));
        assert_eq!(grep(&sandbox, &query("needle")), "in.txt:1: needle in");
    }

    #[test]
    fn a_link_inside_the_workspace_is_not_entered_either() {
        let (d, _s) = workspace(&[("real/a.txt", "needle\n")]);
        let sandbox = Sandbox::new(d.path());
        link_dir(&d.path().join("real"), &d.path().join("alias"));
        assert_eq!(grep(&sandbox, &query("needle")), "real/a.txt:1: needle");
    }

    #[test]
    fn a_file_symlink_out_of_the_workspace_is_not_read() {
        let (d, _s) = workspace(&[
            ("ws/in.txt", "needle in\n"),
            ("outside/secret.txt", "needle out\n"),
        ]);
        let ws = d.path().join("ws");
        let sandbox = Sandbox::new(&ws);
        if !link_file(&d.path().join("outside/secret.txt"), &ws.join("peek.txt")) {
            return;
        }
        assert_eq!(grep(&sandbox, &query("needle")), "in.txt:1: needle in");
    }

    #[test]
    fn a_file_symlink_to_a_denied_file_is_not_read() {
        let (_d, s) = workspace(&[(".env", "needle\n"), ("in.txt", "needle\n")]);
        if !link_file(&s.root().join(".env"), &s.root().join("peek.txt")) {
            return;
        }
        assert_eq!(grep(&s, &query("needle")), "in.txt:1: needle");
    }

    #[cfg(unix)]
    #[test]
    fn a_fifo_in_the_workspace_is_skipped_not_opened() {
        let (_d, s) = workspace(&[(
            "in.txt", "needle
",
        )]);
        let made = std::process::Command::new("mkfifo")
            .arg(s.root().join("a-pipe.txt"))
            .status()
            .unwrap();
        assert!(made.success());
        // `a-pipe.txt` sorts first: opening it would block this test forever.
        assert_eq!(grep(&s, &query("needle")), "in.txt:1: needle");
    }

    #[test]
    fn searching_a_subdirectory_reports_workspace_relative_paths() {
        let (_d, s) = workspace(&[("src/a.rs", "needle\n"), ("other.rs", "needle\n")]);
        assert_eq!(
            grep(
                &s,
                &Query {
                    directory: "src",
                    ..query("needle")
                }
            ),
            "src/a.rs:1: needle"
        );
    }
}
