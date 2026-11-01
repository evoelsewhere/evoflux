//! Shared ignore policy for the filesystem tools (`_ignore.py`).

use std::path::Path;

use regex::Regex;

use crate::fnmatch::{fnmatchcase, translate};
use crate::pyfmt::{splitlines, strip};

pub(crate) const SKIPPED_DIR_NAMES: [&str; 8] = [
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
];

pub(crate) fn is_skipped_dir(name: &str) -> bool {
    SKIPPED_DIR_NAMES.contains(&name)
}

/// The root `.gitignore` rules, plus the combined expressions Python builds
/// when no rule is a `!` negation.
pub(crate) struct Rules {
    rules: Vec<(String, bool)>,
    combined: Option<Combined>,
}

struct Combined {
    dir: Regex,
    file: Regex,
}

impl Rules {
    pub(crate) fn empty() -> Self {
        Self::new(Vec::new())
    }

    fn new(rules: Vec<(String, bool)>) -> Self {
        let combined = if rules.iter().any(|(_, include)| *include) {
            None
        } else {
            combined_expression(&rules, true).zip(combined_expression(&rules, false))
        }
        .map(|(dir, file)| Combined { dir, file });
        Self { rules, combined }
    }

    /// `load_gitignore_rules`: a missing or unreadable file means no rules.
    /// Runs inside `evoflux_core::blocking::run`.
    #[allow(clippy::disallowed_methods)]
    pub(crate) fn load(root: &Path) -> Self {
        let gitignore = root.join(".gitignore");
        if !gitignore.is_file() {
            return Self::empty();
        }
        let Ok(bytes) = std::fs::read(&gitignore) else {
            return Self::empty();
        };
        let Ok(text) = String::from_utf8(bytes) else {
            return Self::empty();
        };
        // `read_text` translates newlines before `splitlines` runs.
        let text = text.replace("\r\n", "\n").replace('\r', "\n");
        Self::from_lines(&text)
    }

    pub(crate) fn from_lines(text: &str) -> Self {
        let mut rules = Vec::new();
        for line in splitlines(text) {
            let mut pattern = strip(line.body);
            if pattern.is_empty() || pattern.starts_with('#') {
                continue;
            }
            let include = pattern.starts_with('!');
            if include {
                pattern = strip(pattern.get(1..).unwrap_or_default());
            }
            if !pattern.is_empty() {
                rules.push((pattern.to_owned(), include));
            }
        }
        Self::new(rules)
    }

    /// `is_gitignored(rel, is_dir=..., rules=...)`; `rel` uses `/` separators.
    pub(crate) fn is_ignored(&self, rel: &str, is_dir: bool) -> bool {
        if let Some(combined) = &self.combined {
            let regex = if is_dir {
                &combined.dir
            } else {
                &combined.file
            };
            return regex.is_match(rel);
        }
        let parts: Vec<&str> = rel.split('/').collect();
        let mut ignored = false;
        for (pattern, include) in &self.rules {
            if matches_pattern(pattern, rel, is_dir, &parts) {
                ignored = !include;
            }
        }
        ignored
    }
}

/// `(directory_only, normalized, contains_slash)`.
fn normalized_pattern(pattern: &str) -> (bool, &str, bool) {
    let directory_only = pattern.ends_with('/');
    let normalized = if directory_only {
        pattern.trim_matches('/')
    } else {
        pattern.trim_start_matches('/')
    };
    (directory_only, normalized, normalized.contains('/'))
}

fn matches_pattern(pattern: &str, rel: &str, is_dir: bool, parts: &[&str]) -> bool {
    let (directory_only, normalized, contains_slash) = normalized_pattern(pattern);
    if normalized.is_empty() {
        return false;
    }
    if directory_only {
        return if is_dir {
            rel == normalized
        } else {
            rel.starts_with(&format!("{normalized}/"))
        };
    }
    if contains_slash {
        return fnmatchcase(rel, normalized) || fnmatchcase(rel, &format!("{normalized}/*"));
    }
    parts.iter().any(|part| fnmatchcase(part, normalized))
}

/// `_combined_exclusion_pattern`: one alternation for an exclusion-only rule set.
fn combined_expression(rules: &[(String, bool)], is_dir: bool) -> Option<Regex> {
    let mut expressions: Vec<String> = Vec::new();
    for (pattern, _) in rules {
        let (directory_only, normalized, contains_slash) = normalized_pattern(pattern);
        if normalized.is_empty() {
            continue;
        }
        if directory_only {
            let expression = regex::escape(normalized);
            expressions.push(if is_dir {
                format!("^(?:{expression})$")
            } else {
                format!("^(?:{expression})/")
            });
            continue;
        }
        let translated = translate(normalized);
        let body = translated.strip_prefix("(?s)^(?:")?.strip_suffix(")\\z")?;
        expressions.push(if contains_slash {
            format!("(?s)^(?:{body})(?:/.*)?$")
        } else {
            format!("(?s)(?:^|/)(?:{body})(?:/|$)")
        });
    }
    if expressions.is_empty() {
        return Regex::new("[^\\s\\S]").ok();
    }
    // Each expression carries its own flags, so group them before alternating.
    let grouped: Vec<String> = expressions.iter().map(|e| format!("(?:{e})")).collect();
    Regex::new(&grouped.join("|")).ok()
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

    fn rules(text: &str) -> Rules {
        Rules::from_lines(text)
    }

    #[test]
    fn skipped_dirs_are_the_python_set() {
        for name in [
            "node_modules",
            "dist",
            "build",
            ".venv",
            "venv",
            "__pycache__",
            ".ruff_cache",
            ".pytest_cache",
        ] {
            assert!(is_skipped_dir(name), "{name}");
        }
        assert!(!is_skipped_dir("src"));
        assert!(!is_skipped_dir("Build"));
    }

    #[test]
    fn comments_blanks_and_negations_parse() {
        let r = rules("# c\n\n  *.log  \n!keep.log\n!  \n/rooted\n");
        assert_eq!(
            r.rules,
            vec![
                ("*.log".to_owned(), false),
                ("keep.log".to_owned(), true),
                ("/rooted".to_owned(), false)
            ]
        );
        assert!(
            r.combined.is_none(),
            "a negation disables the combined form"
        );
        assert!(rules("*.log\n").combined.is_some());
    }

    #[test]
    fn exclusion_only_sets_use_combined_semantics() {
        let r = rules("*.log\nbuild/\ndocs/*.tmp\n");
        assert!(r.is_ignored("a.log", false));
        assert!(r.is_ignored("x/y/a.log", false));
        assert!(r.is_ignored("x/a.log/inner", false));
        assert!(!r.is_ignored("a.txt", false));
        assert!(r.is_ignored("build", true));
        assert!(
            !r.is_ignored("build", false),
            "dir-only pattern vs a file named build"
        );
        assert!(r.is_ignored("build/x.o", false));
        assert!(
            !r.is_ignored("src/build", true),
            "dir-only matches the whole rel path"
        );
        assert!(r.is_ignored("docs/a.tmp", false));
        assert!(r.is_ignored("docs/a.tmp/x", false));
        assert!(!r.is_ignored("other/docs/a.tmp", false));
    }

    #[test]
    fn combined_star_crosses_separators_like_python() {
        let r = rules("a*b\n");
        assert!(r.is_ignored("a/xb", false));
        assert!(r.is_ignored("axb", false));
    }

    #[test]
    fn negation_sets_use_last_match_wins() {
        let r = rules("*.log\n!keep.log\n");
        assert!(r.is_ignored("a.log", false));
        assert!(!r.is_ignored("keep.log", false));
        assert!(!r.is_ignored("sub/keep.log", false));
        let r = rules("!keep.log\n*.log\n");
        assert!(r.is_ignored("keep.log", false));
    }

    #[test]
    fn sequential_rules_match_each_pattern_shape() {
        let r = rules("!zzz\nbuild/\ndocs/*.tmp\nname\n/anchored\n");
        assert!(r.is_ignored("build", true));
        assert!(!r.is_ignored("build", false));
        assert!(r.is_ignored("build/x", false));
        assert!(r.is_ignored("docs/a.tmp", false));
        assert!(r.is_ignored("docs/a.tmp/sub", false));
        assert!(r.is_ignored("x/name", false));
        assert!(r.is_ignored("name/x", false));
        assert!(r.is_ignored("anchored", false));
        assert!(!r.is_ignored("x/other", false));
    }

    #[test]
    fn empty_rule_sets_ignore_nothing() {
        assert!(!Rules::empty().is_ignored("anything", false));
        assert!(!rules("/\n").is_ignored("anything", false));
    }

    #[test]
    fn load_reads_utf8_gitignore_and_tolerates_absence() {
        let dir = tempfile::tempdir().unwrap();
        assert!(!Rules::load(dir.path()).is_ignored("a.log", false));
        std::fs::write(dir.path().join(".gitignore"), "*.log\r\n#x\r\nout/\r\n").unwrap();
        let r = Rules::load(dir.path());
        assert!(r.is_ignored("a.log", false));
        assert!(r.is_ignored("out", true));
        std::fs::write(dir.path().join(".gitignore"), [0xff, 0xfe, b'*']).unwrap();
        assert!(!Rules::load(dir.path()).is_ignored("a.log", false));
    }
}
