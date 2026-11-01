//! `glob`: find files by pattern, newest first (`glob.py`).
//!
//! `match="path"` follows `pathlib.Path.glob` (CPython 3.12) and `match="name"`
//! follows `os.walk` plus `fnmatch`.

use std::collections::HashSet;
use std::ops::ControlFlow;
use std::path::{Path, PathBuf};

use async_trait::async_trait;
use serde_json::{json, Value};

use crate::args::{self, Field, Kind, Val};
use crate::fnmatch::{compiled, fnmatch};
use crate::fsutil::{children, is_dir, is_file, is_link, is_symlink, mtime_ns};
use crate::ignore::{is_skipped_dir, Rules};
use crate::sandbox::{is_under, resolve, Sandbox};
use crate::{definition, property, run_blocking, search_root, Tool, ToolCtx, ToolOutput};

pub(crate) struct GlobTool;

/// Matches collected before sorting; beyond this the total is reported as "N+".
const MAX_SCAN: usize = 20_000;

const DESCRIPTION: &str =
    "Find files by glob pattern. Use match='path' (default) for full-path patterns \
like 'src/**/*.ts', or match='name' for filename-only like '*.py'. \
Results are sorted by modification time, newest first; a partial page \
ends with a notice giving the offset for the next page. Preferred over \
shell find or ls for locating files by name.";

fn fields() -> Vec<Field> {
    vec![
        Field::required("pattern", Kind::Str),
        Field::optional("directory", Kind::Str, Val::Str(".".into())),
        Field::optional("match", Kind::Str, Val::Str("path".into())),
        Field::optional("max_results", Kind::Int, Val::Int(200)),
        Field::optional("offset", Kind::Int, Val::Int(0)),
    ]
}

/// `(mtime, display path)`.
type Hit = (i128, String);

fn newest_first(mut hits: Vec<Hit>) -> Vec<String> {
    hits.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    hits.into_iter().map(|(_, path)| path).collect()
}

/// Slice one page and end a partial page with a notice for the model.
fn page(matches: &[String], offset: i64, limit: i64) -> Vec<String> {
    let total = matches.len();
    let shown = if total >= MAX_SCAN {
        format!("{total}+")
    } else {
        total.to_string()
    };
    let start = usize::try_from(offset).unwrap_or(usize::MAX);
    if start >= total {
        return vec![format!(
            "No entries at offset {offset} — only {shown} files."
        )];
    }
    let take = usize::try_from(limit).unwrap_or(usize::MAX);
    let mut out: Vec<String> = matches.iter().skip(start).take(take).cloned().collect();
    let end = start + out.len();
    if end < total {
        out.push(format!(
            "[Showing files {}-{end} of {shown}, newest first. Pass \
             offset={end} for the next page, or narrow the pattern or directory.]",
            start + 1
        ));
    } else if start > 0 {
        out.push(format!("[Showing files {}-{end} of {shown}.]", start + 1));
    }
    out
}

/// `os.walk` + `fnmatch` over file names.
fn scan_name(sandbox: &Sandbox, root: &Path, pattern: &str, rules: &Rules) -> Vec<String> {
    let mut hits: Vec<Hit> = Vec::new();
    let mut stack: Vec<PathBuf> = vec![root.to_path_buf()];
    while let Some(current) = stack.pop() {
        let mut dirs: Vec<(String, PathBuf)> = Vec::new();
        let mut files: Vec<(String, PathBuf)> = Vec::new();
        for (name, path) in children(&current) {
            if is_dir(&path) {
                dirs.push((name, path));
            } else {
                files.push((name, path));
            }
        }
        for (name, path) in dirs {
            let rel = rel_posix(&path, root);
            // A symlinked directory is listed by `os.walk` but never entered.
            if !name.starts_with('.')
                && !is_skipped_dir(&name)
                && !rules.is_ignored(&rel, true)
                && !is_symlink(&path)
                && sandbox.permits_link(&path)
            {
                stack.push(path);
            }
        }
        for (name, path) in files {
            if name.starts_with('.') {
                continue;
            }
            if rules.is_ignored(&rel_posix(&path, root), false) {
                continue;
            }
            if fnmatch(&name, pattern) {
                hits.push((mtime_ns(&path), sandbox.display_path(&path)));
                if hits.len() >= MAX_SCAN {
                    return newest_first(hits);
                }
            }
        }
    }
    newest_first(hits)
}

pub(crate) fn rel_posix(path: &Path, root: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .components()
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect::<Vec<_>>()
        .join("/")
}

/// The parts `pathlib` derives from a glob pattern, or its refusal.
fn pattern_parts(pattern: &str) -> Result<Vec<String>, String> {
    if pattern.is_empty() {
        return Err("Unacceptable pattern: ''".to_owned());
    }
    let windows = cfg!(windows);
    let is_sep = |c: char| c == '/' || (windows && c == '\\');
    let first = pattern.chars().next();
    let second = pattern.chars().nth(1);
    let has_drive =
        windows && second == Some(':') && first.is_some_and(|c| c.is_ascii_alphabetic());
    if has_drive || first.is_some_and(is_sep) {
        // Not a ValueError/OSError, so Python's wrapper adds the class name.
        return Err(
            "Tool 'glob' raised NotImplementedError: Non-relative patterns are unsupported"
                .to_owned(),
        );
    }
    let mut parts: Vec<String> = pattern
        .split(is_sep)
        .filter(|part| !part.is_empty() && *part != ".")
        .map(str::to_owned)
        .collect();
    if pattern.ends_with(is_sep) {
        parts.push(String::new());
    }
    Ok(parts)
}

/// Whether `link` (a symlink) leads outside the workspace.
fn escapes(sandbox: &Sandbox, path: &Path) -> bool {
    is_link(path) && !resolve(path).is_some_and(|real| is_under(&real, sandbox.root()))
}

struct Selector<'a> {
    sandbox: &'a Sandbox,
    ignore_case: bool,
    sink: &'a mut dyn FnMut(PathBuf) -> ControlFlow<()>,
}

impl Selector<'_> {
    /// One step of `pathlib`'s selector chain for the remaining `parts`.
    fn select(&mut self, parent: &Path, parts: &[String]) -> ControlFlow<()> {
        let Some((pat, rest)) = parts.split_first() else {
            return (self.sink)(parent.to_path_buf());
        };
        if pat.is_empty() {
            return (self.sink)(parent.to_path_buf());
        }
        if pat == ".." {
            // Every result below a `..` has a hidden part and is dropped, so
            // nothing outside the search root is listed to find that out.
            return ControlFlow::Continue(());
        }
        if pat == "**" {
            let rest: &[String] = {
                let skip = parts.iter().take_while(|p| *p == "**").count();
                parts.get(skip..).unwrap_or_default()
            };
            let mut seen: HashSet<PathBuf> = HashSet::new();
            let mut dirs = Vec::new();
            collect_directories(self.sandbox, parent, &mut dirs);
            for dir in dirs {
                let mut found = Vec::new();
                let mut inner = Selector {
                    sandbox: self.sandbox,
                    ignore_case: self.ignore_case,
                    sink: &mut |p| {
                        found.push(p);
                        ControlFlow::Continue(())
                    },
                };
                let _ = inner.select(&dir, rest);
                for path in found {
                    if seen.insert(path.clone()) {
                        (self.sink)(path)?;
                    }
                }
            }
            return ControlFlow::Continue(());
        }
        // Every other part, literal or not, is matched against the real entry
        // names (`_WildcardSelector`), so the listing shows the on-disk case.
        let dironly = !rest.is_empty();
        let Some(regex) = compiled(pat, self.ignore_case) else {
            return ControlFlow::Continue(());
        };
        for (name, path) in children(parent) {
            if dironly && !is_dir(&path) {
                continue;
            }
            if regex.is_match(&name) {
                if dironly && escapes(self.sandbox, &path) {
                    continue;
                }
                self.select(&path, rest)?;
            }
        }
        ControlFlow::Continue(())
    }
}

/// `_iterate_directories`: the start and every real subdirectory below it.
///
/// Hidden and generated directories are not entered: nothing under them can
/// survive the tool's own filters.
fn collect_directories(sandbox: &Sandbox, start: &Path, out: &mut Vec<PathBuf>) {
    out.push(start.to_path_buf());
    for (name, path) in children(start) {
        let real_dir = !is_symlink(&path) && is_dir(&path) && sandbox.permits_link(&path);
        if real_dir && !name.starts_with('.') && !is_skipped_dir(&name) {
            collect_directories(sandbox, &path, out);
        }
    }
}

fn scan_path(
    sandbox: &Sandbox,
    root: &Path,
    pattern: &str,
    rules: &Rules,
) -> Result<Vec<String>, String> {
    let parts = pattern_parts(pattern)?;
    if parts.is_empty() {
        // pathlib indexes the first part of "." and finds none.
        return Err("Tool 'glob' raised IndexError: tuple index out of range".to_owned());
    }
    if parts.iter().any(|part| part != "**" && part.contains("**")) {
        return Err("Invalid pattern: '**' can only be an entire path component".to_owned());
    }
    let mut hits: Vec<Hit> = Vec::new();
    let mut sink = |m: PathBuf| {
        if !is_file(&m) {
            return ControlFlow::Continue(());
        }
        let rel = m.strip_prefix(root).unwrap_or(&m);
        let names: Vec<String> = rel
            .components()
            .map(|c| c.as_os_str().to_string_lossy().into_owned())
            .collect();
        if names.iter().any(|part| part.starts_with('.')) {
            return ControlFlow::Continue(());
        }
        let (_, dirs) = names.split_last().unwrap_or((&String::new(), &[]));
        if dirs.iter().any(|part| is_skipped_dir(part)) {
            return ControlFlow::Continue(());
        }
        if rules.is_ignored(&names.join("/"), false) {
            return ControlFlow::Continue(());
        }
        hits.push((mtime_ns(&m), sandbox.display_path(&m)));
        if hits.len() >= MAX_SCAN {
            ControlFlow::Break(())
        } else {
            ControlFlow::Continue(())
        }
    };
    let mut selector = Selector {
        sandbox,
        ignore_case: cfg!(windows),
        sink: &mut sink,
    };
    let _ = selector.select(root, &parts);
    Ok(newest_first(hits))
}

pub(crate) fn run(
    sandbox: &Sandbox,
    pattern: &str,
    directory: &str,
    match_mode: &str,
    max_results: i64,
    offset: i64,
) -> Result<String, String> {
    let resolved = search_root::validate(sandbox, directory, "glob")?;
    let rules = Rules::load(&resolved);
    let matches = if match_mode == "name" {
        scan_name(sandbox, &resolved, pattern, &rules)
    } else {
        scan_path(sandbox, &resolved, pattern, &rules)?
    };
    if matches.is_empty() {
        return Ok(format!(
            "No files matching '{pattern}' in {}",
            sandbox.display_path(&resolved)
        ));
    }
    Ok(page(&matches, offset.max(0), max_results.max(1)).join("\n"))
}

#[async_trait]
impl Tool for GlobTool {
    fn name(&self) -> &str {
        "glob"
    }

    fn spec(&self) -> Value {
        definition(
            "glob",
            DESCRIPTION,
            json!({
                "pattern": property(None, "Glob pattern. Use '**/*.py' or 'src/**/*.ts' to match by full path, or '*.py' with match='name' to match filename only.", &[("type", json!("string"))]),
                "directory": property(Some(json!(".")), "Search root (default '.' = workspace root).", &[("type", json!("string"))]),
                "match": property(Some(json!("path")), "Match against 'path' (default) or 'name' (filename only).", &[("type", json!("string"))]),
                "max_results": property(Some(json!(200)), "Maximum number of results to return (default 200).", &[("type", json!("integer"))]),
                "offset": property(Some(json!(0)), "Skip this many files first. Use the offset a truncation notice gives to fetch the next page.", &[("type", json!("integer"))]),
            }),
            &["pattern"],
        )
    }

    async fn call(&self, args: Value, ctx: &ToolCtx) -> ToolOutput {
        let parsed = match args::parse("glob", &fields(), &args) {
            Ok(parsed) => parsed,
            Err(message) => return ToolOutput::error(&message),
        };
        let root = ctx.workspace_root.clone();
        run_blocking("glob", move || {
            run(
                &Sandbox::new(&root),
                &parsed.str("pattern"),
                &parsed.str("directory"),
                &parsed.str("match"),
                parsed.int("max_results"),
                parsed.int("offset"),
            )
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
    use crate::testutil::{link_dir, set_mtime, workspace};

    fn names(count: usize) -> Vec<String> {
        (0..count).map(|i| format!("f{i}")).collect()
    }

    fn glob(sandbox: &Sandbox, pattern: &str, directory: &str, mode: &str) -> String {
        run(sandbox, pattern, directory, mode, 200, 0).unwrap()
    }

    fn sorted_lines(text: &str) -> Vec<String> {
        let mut lines: Vec<String> = text.lines().map(str::to_owned).collect();
        lines.sort();
        lines
    }

    #[test]
    fn newest_first_sorts_by_time_then_path() {
        let hits = vec![
            (5, "b".to_owned()),
            (9, "z".to_owned()),
            (5, "a".to_owned()),
            (-1, "old".to_owned()),
        ];
        assert_eq!(newest_first(hits), vec!["z", "a", "b", "old"]);
    }

    #[test]
    fn page_without_a_cut_has_no_notice() {
        assert_eq!(page(&names(3), 0, 10), vec!["f0", "f1", "f2"]);
        assert_eq!(page(&names(3), 0, 3), vec!["f0", "f1", "f2"]);
    }

    #[test]
    fn page_cut_names_the_next_offset() {
        assert_eq!(
            page(&names(5), 0, 2),
            vec![
                "f0",
                "f1",
                "[Showing files 1-2 of 5, newest first. Pass offset=2 for the next page, or narrow the pattern or directory.]"
            ]
        );
        assert_eq!(
            page(&names(5), 2, 2).last().unwrap(),
            "[Showing files 3-4 of 5, newest first. Pass offset=4 for the next page, or narrow the pattern or directory.]"
        );
    }

    #[test]
    fn last_partial_page_is_labelled() {
        assert_eq!(
            page(&names(5), 4, 2),
            vec!["f4", "[Showing files 5-5 of 5.]"]
        );
        assert_eq!(
            page(&names(5), 3, 2).last().unwrap(),
            "[Showing files 4-5 of 5.]"
        );
    }

    #[test]
    fn page_past_the_end_says_so() {
        assert_eq!(
            page(&names(3), 3, 5),
            vec!["No entries at offset 3 — only 3 files."]
        );
        assert_eq!(
            page(&names(3), 99, 5),
            vec!["No entries at offset 99 — only 3 files."]
        );
    }

    #[test]
    fn a_full_scan_reports_a_lower_bound() {
        let many = names(MAX_SCAN);
        assert_eq!(
            page(&many, MAX_SCAN as i64, 5),
            vec!["No entries at offset 20000 — only 20000+ files."]
        );
        assert!(page(&many, 0, 2).last().unwrap().contains("of 20000+,"));
        assert!(page(&names(MAX_SCAN - 1), 0, 2)
            .last()
            .unwrap()
            .contains("of 19999,"));
    }

    #[test]
    fn pattern_parts_follow_pathlib() {
        let parts = |p: &str| pattern_parts(p).unwrap();
        assert_eq!(parts("src/**/*.rs"), vec!["src", "**", "*.rs"]);
        assert_eq!(parts("./a//b/./c"), vec!["a", "b", "c"]);
        assert_eq!(parts("a/"), vec!["a", ""]);
        assert_eq!(parts("../x"), vec!["..", "x"]);
        assert!(parts(".").is_empty());
        assert_eq!(pattern_parts("").unwrap_err(), "Unacceptable pattern: ''");
        assert_eq!(
            pattern_parts("/abs").unwrap_err(),
            "Tool 'glob' raised NotImplementedError: Non-relative patterns are unsupported"
        );
        let backslash = parts(r"a\b");
        if cfg!(windows) {
            assert_eq!(backslash, vec!["a", "b"]);
        } else {
            assert_eq!(backslash, vec![r"a\b"]);
        }
    }

    #[cfg(windows)]
    #[test]
    fn windows_drive_and_rooted_patterns_are_not_relative() {
        for pattern in ["C:x", "C:/x", r"\x", r"\\host\share"] {
            assert!(pattern_parts(pattern).is_err(), "{pattern}");
        }
        assert!(pattern_parts("1:x").is_ok(), "only a letter makes a drive");
    }

    #[test]
    fn path_mode_matches_nested_and_skips_hidden_and_generated() {
        let (_d, s) = workspace(&[
            ("a.rs", ""),
            ("src/b.rs", ""),
            ("src/deep/c.rs", ""),
            (".hid/d.rs", ""),
            ("node_modules/e.rs", ""),
            ("src/.f.rs", ""),
            ("src/build/g.rs", ""),
        ]);
        assert_eq!(
            sorted_lines(&glob(&s, "**/*.rs", ".", "path")),
            vec!["a.rs", "src/b.rs", "src/deep/c.rs"]
        );
        assert_eq!(glob(&s, "*.rs", ".", "path"), "a.rs");
        assert_eq!(glob(&s, "src/*.rs", ".", "path"), "src/b.rs");
    }

    #[test]
    fn literal_parts_are_matched_against_the_directory_listing() {
        let (_d, s) = workspace(&[("src/b.rs", "")]);
        assert_eq!(glob(&s, "src/b.rs", ".", "path"), "src/b.rs");
        let upper = glob(&s, "SRC/B.RS", ".", "path");
        if cfg!(windows) {
            assert_eq!(upper, "src/b.rs", "the listing shows the on-disk case");
        } else {
            assert!(upper.starts_with("No files matching"));
        }
    }

    #[test]
    fn parent_parts_list_nothing() {
        let (_d, s) = workspace(&[("a.txt", ""), ("src/b.txt", "")]);
        for pattern in ["../*", "src/../a.txt", "../ws/a.txt", "*/../a.txt"] {
            assert!(
                glob(&s, pattern, ".", "path").starts_with("No files matching"),
                "{pattern}"
            );
        }
    }

    #[test]
    fn double_star_matches_zero_or_more_directories() {
        let (_d, s) = workspace(&[("a.txt", ""), ("x/b.txt", ""), ("x/y/c.txt", "")]);
        assert_eq!(
            sorted_lines(&glob(&s, "**/**/*.txt", ".", "path")),
            vec!["a.txt", "x/b.txt", "x/y/c.txt"]
        );
        assert_eq!(
            sorted_lines(&glob(&s, "x/**/*.txt", ".", "path")),
            vec!["x/b.txt", "x/y/c.txt"]
        );
        assert!(glob(&s, "**", ".", "path").starts_with("No files matching '**' in "));
    }

    #[test]
    fn a_result_reachable_two_ways_is_listed_once() {
        let (_d, s) = workspace(&[("x/x/y.txt", "")]);
        assert_eq!(glob(&s, "**/x/**/y.txt", ".", "path"), "x/x/y.txt");
    }

    #[test]
    fn the_double_star_check_covers_every_part() {
        let (_d, s) = workspace(&[("a.txt", "")]);
        assert_eq!(
            run(&s, "nothing/a**b", ".", "path", 200, 0).unwrap_err(),
            "Invalid pattern: '**' can only be an entire path component"
        );
        assert!(run(&s, "**/**", ".", "path", 200, 0).is_ok());
    }

    #[test]
    fn dot_pattern_reproduces_the_python_index_error() {
        let (_d, s) = workspace(&[("a.txt", "")]);
        assert_eq!(
            run(&s, ".", ".", "path", 200, 0).unwrap_err(),
            "Tool 'glob' raised IndexError: tuple index out of range"
        );
        assert!(run(&s, "./", ".", "path", 200, 0)
            .unwrap()
            .starts_with("No files matching"));
    }

    #[test]
    fn trailing_separator_selects_directories_only() {
        let (_d, s) = workspace(&[("src/a.rs", "")]);
        assert!(glob(&s, "src/", ".", "path").starts_with("No files matching 'src/' in "));
        assert!(glob(&s, "s*/", ".", "path").starts_with("No files matching"));
    }

    #[test]
    fn an_invalid_class_never_matches() {
        let (_d, s) = workspace(&[("a.txt", "")]);
        assert!(glob(&s, "[z-a].txt", ".", "path").starts_with("No files matching"));
    }

    #[test]
    fn name_mode_matches_file_names_at_any_depth() {
        let (_d, s) = workspace(&[
            ("a.py", ""),
            ("p/b.py", ""),
            ("p/q/c.py", ""),
            ("p/q/c.txt", ""),
            (".h/d.py", ""),
            ("p/.e.py", ""),
        ]);
        assert_eq!(
            sorted_lines(&glob(&s, "*.py", ".", "name")),
            vec!["a.py", "p/b.py", "p/q/c.py"]
        );
    }

    #[test]
    fn name_mode_honours_the_gitignore_and_skips_generated_dirs() {
        let (_d, s) = workspace(&[
            (".gitignore", "*.log\nkeep_out/\n"),
            ("a.log", ""),
            ("b.txt", ""),
            ("keep_out/c.txt", ""),
            ("dist/d.txt", ""),
            ("sub/e.log", ""),
            ("sub/f.txt", ""),
        ]);
        assert_eq!(
            sorted_lines(&glob(&s, "*", ".", "name")),
            vec!["b.txt", "sub/f.txt"]
        );
    }

    #[test]
    fn path_mode_honours_the_gitignore() {
        let (_d, s) = workspace(&[
            (".gitignore", "*.log\nkeep_out/\n"),
            ("a.log", ""),
            ("b.txt", ""),
            ("keep_out/c.txt", ""),
        ]);
        assert_eq!(glob(&s, "**/*", ".", "path"), "b.txt");
    }

    #[test]
    fn results_are_newest_first() {
        let (d, s) = workspace(&[("old.txt", ""), ("new.txt", ""), ("mid.txt", "")]);
        set_mtime(&d.path().join("old.txt"), 1_000);
        set_mtime(&d.path().join("mid.txt"), 2_000);
        set_mtime(&d.path().join("new.txt"), 3_000);
        assert_eq!(glob(&s, "*.txt", ".", "path"), "new.txt\nmid.txt\nold.txt");
        assert_eq!(glob(&s, "*.txt", ".", "name"), "new.txt\nmid.txt\nold.txt");
    }

    #[test]
    fn a_missing_match_names_the_search_root() {
        let (_d, s) = workspace(&[("src/a.txt", "")]);
        assert_eq!(
            glob(&s, "*.zzz", "src", "path"),
            "No files matching '*.zzz' in src"
        );
        assert_eq!(
            glob(&s, "*.zzz", ".", "path"),
            format!("No files matching '*.zzz' in {}", s.root().display())
        );
    }

    #[test]
    fn paging_arguments_are_clamped() {
        let (_d, s) = workspace(&[("a.txt", ""), ("b.txt", ""), ("c.txt", "")]);
        let out = run(&s, "*.txt", ".", "path", 0, -3).unwrap();
        let lines: Vec<&str> = out.lines().collect();
        assert_eq!(lines.len(), 2, "limit 0 acts as 1: {out}");
        assert!(lines[1].starts_with("[Showing files 1-1 of 3,"), "{out}");
        let out = run(&s, "*.txt", ".", "path", -9, 0).unwrap();
        assert_eq!(out.lines().count(), 2);
    }

    #[test]
    fn a_link_leading_out_of_the_workspace_is_not_followed() {
        let (d, _s) = workspace(&[("ws/in.txt", ""), ("outside/secret.txt", "x")]);
        let ws = d.path().join("ws");
        let sandbox = Sandbox::new(&ws);
        link_dir(&d.path().join("outside"), &ws.join("escape"));
        let none = |pattern: &str| {
            format!(
                "No files matching '{pattern}' in {}",
                sandbox.root().display()
            )
        };
        assert_eq!(
            glob(&sandbox, "escape/*.txt", ".", "path"),
            none("escape/*.txt")
        );
        assert_eq!(
            glob(&sandbox, "*/secret.txt", ".", "path"),
            none("*/secret.txt")
        );
        assert_eq!(glob(&sandbox, "**/*.txt", ".", "path"), "in.txt");
        assert_eq!(glob(&sandbox, "*.txt", ".", "name"), "in.txt");
    }

    #[test]
    fn a_link_inside_the_workspace_is_followed_by_explicit_components_only() {
        let (d, _s) = workspace(&[("real/a.txt", "")]);
        let sandbox = Sandbox::new(d.path());
        link_dir(&d.path().join("real"), &d.path().join("alias"));
        assert_eq!(glob(&sandbox, "alias/*.txt", ".", "path"), "alias/a.txt");
        assert_eq!(
            glob(&sandbox, "**/*.txt", ".", "path"),
            "real/a.txt",
            "`**` does not enter a link"
        );
    }
}
