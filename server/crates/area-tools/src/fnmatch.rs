//! Python's `fnmatch` module: `translate`, `fnmatchcase` and the OS-aware
//! `fnmatch`, compiled to `regex` with the same dot-all, full-match meaning.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

use regex::Regex;

/// Port of `fnmatch.translate` (CPython 3.12) producing a `regex` crate source.
pub(crate) fn translate(pat: &str) -> String {
    let chars: Vec<char> = pat.chars().collect();
    let at = |i: usize| chars.get(i).copied();
    let mut res: Vec<String> = Vec::new();
    let mut i = 0;
    // Every pass consumes a character, so `len` passes are enough.
    for _ in 0..chars.len() {
        let Some(c) = at(i) else { break };
        i += 1;
        match c {
            '*' => {
                if res.last().map(String::as_str) != Some(".*") {
                    res.push(".*".to_owned());
                }
            }
            '?' => res.push(".".to_owned()),
            '[' => {
                // A `!` and then a `]` right after `[` belong to the class.
                let body = i + usize::from(at(i) == Some('!'));
                let body = body + usize::from(at(body) == Some(']'));
                let close = (body..chars.len()).find(|&p| at(p) == Some(']'));
                let Some(j) = close else {
                    res.push("\\[".to_owned());
                    continue;
                };
                let stuff: Vec<char> = chars.get(i..j).unwrap_or_default().to_vec();
                let mut class = if stuff.contains(&'-') {
                    class_with_ranges(&chars, i, j)
                } else {
                    stuff.iter().map(|c| escape_class_char(*c)).collect()
                };
                class = escape_set_ops(&class);
                i = j + 1;
                if class.is_empty() {
                    res.push("[^\\s\\S]".to_owned());
                } else if class == "!" {
                    res.push(".".to_owned());
                } else {
                    if let Some(rest) = class.strip_prefix('!') {
                        class = format!("^{rest}");
                    } else if class.starts_with('^') || class.starts_with('[') {
                        class = format!("\\{class}");
                    }
                    res.push(format!("[{class}]"));
                }
            }
            c => res.push(regex::escape(&c.to_string())),
        }
    }
    format!("(?s)^(?:{})\\z", res.concat())
}

/// `\` doubles and a literal `-` is escaped (range dashes come from the join).
fn escape_class_char(c: char) -> String {
    match c {
        '\\' => "\\\\".to_owned(),
        '-' => "\\-".to_owned(),
        c => c.to_string(),
    }
}

fn class_with_ranges(chars: &[char], start: usize, end: usize) -> String {
    let at = |i: usize| chars.get(i).copied();
    let mut i = start;
    let mut chunks: Vec<Vec<char>> = Vec::new();
    // A `-` first in the class (after an optional `!`) is a literal.
    let mut k = i + 1 + usize::from(at(i) == Some('!'));
    // Each dash found ends a chunk; there can be at most one per character.
    for _ in start..end {
        let found = (k..end).find(|&p| at(p) == Some('-'));
        let Some(dash) = found else { break };
        chunks.push(chars.get(i..dash).unwrap_or_default().to_vec());
        i = dash + 1;
        k = dash + 3;
    }
    let chunk: Vec<char> = chars.get(i..end).unwrap_or_default().to_vec();
    if chunk.is_empty() {
        if let Some(last) = chunks.last_mut() {
            last.push('-');
        }
    } else {
        chunks.push(chunk);
    }
    // Remove empty ranges: they are invalid in a regex class.
    for idx in (1..chunks.len()).rev() {
        let prev = idx - 1;
        let prev_last = chunks.get(prev).and_then(|c| c.last().copied());
        let next_first = chunks.get(idx).and_then(|c| c.first().copied());
        if let (Some(prev_last), Some(next_first)) = (prev_last, next_first) {
            if prev_last > next_first {
                let next: Vec<char> = chunks.get(idx).cloned().unwrap_or_default();
                if let Some(before) = chunks.get_mut(prev) {
                    before.pop();
                    before.extend(next.iter().skip(1));
                }
                chunks.remove(idx);
            }
        }
    }
    chunks
        .iter()
        .map(|chunk| {
            chunk
                .iter()
                .map(|c| escape_class_char(*c))
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("-")
}

/// `re.sub(r"([&~|])", r"\\\1", stuff)`.
fn escape_set_ops(class: &str) -> String {
    let mut out = String::with_capacity(class.len());
    for c in class.chars() {
        if matches!(c, '&' | '~' | '|') {
            out.push('\\');
        }
        out.push(c);
    }
    out
}

/// Maximum compiled patterns retained, including invalid patterns.
const MAX_CACHE_ENTRIES: usize = 4096;

/// Compile `translate(pat)`, remembering the result; `None` when it is not a valid regex.
pub(crate) fn compiled(pat: &str, ignore_case: bool) -> Option<Arc<Regex>> {
    type Cache = Mutex<HashMap<(String, bool), Option<Arc<Regex>>>>;
    static CACHE: OnceLock<Cache> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    let key = (pat.to_owned(), ignore_case);
    {
        let guard = cache.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(hit) = guard.get(&key) {
            return hit.clone();
        }
    }
    let source = if ignore_case {
        format!("(?i){}", translate(pat))
    } else {
        translate(pat)
    };
    let regex = Regex::new(&source).ok().map(Arc::new);
    let mut guard = cache.lock().unwrap_or_else(|e| e.into_inner());
    if guard.len() >= MAX_CACHE_ENTRIES {
        guard.clear();
    }
    guard.insert(key, regex.clone());
    regex
}

/// `fnmatch.fnmatchcase`.
pub(crate) fn fnmatchcase(name: &str, pat: &str) -> bool {
    compiled(pat, false).is_some_and(|re| re.is_match(name))
}

/// `os.path.normcase`: Windows lowercases and uses backslashes.
fn normcase(s: &str) -> String {
    if cfg!(windows) {
        s.to_lowercase().replace('/', "\\")
    } else {
        s.to_owned()
    }
}

/// `fnmatch.fnmatch`: case rules follow the host OS.
pub(crate) fn fnmatch(name: &str, pat: &str) -> bool {
    fnmatchcase(&normcase(name), &normcase(pat))
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

    fn case(name: &str, pat: &str) -> bool {
        fnmatchcase(name, pat)
    }

    #[test]
    fn star_question_and_literals() {
        assert!(case("main.py", "*.py"));
        assert!(!case("main.pyc", "*.py"));
        assert!(case("a/b.py", "*.py"), "star crosses separators");
        assert!(case("abc", "a?c"));
        assert!(!case("ac", "a?c"));
        assert!(case("a\nb", "a*b"), "dot-all");
        assert!(case("a.b", "a.b"));
        assert!(!case("axb", "a.b"), "dot is literal");
        assert!(case("a+b(c)", "a+b(c)"));
        assert!(case("a|b", "a|b"));
        assert!(case("{", "{"));
        assert!(case("**/.env", "**/.env"));
        assert!(case("x/y/.env", "**/.env"));
        assert!(case("x/.env.local", "**/.env.*"));
        assert!(!case(".env", "**/.env"));
        assert!(!case("x/.envrc", "**/.env"));
        assert!(case("", "*"));
        assert!(!case("", "?"));
    }

    #[test]
    fn classes_match_python() {
        // Every row was checked against CPython 3.12 `fnmatch.fnmatchcase`.
        for (name, pat, want) in [
            ("a", "[abc]", true),
            ("d", "[abc]", false),
            ("d", "[!abc]", true),
            ("a", "[!abc]", false),
            ("m", "[a-z]", true),
            ("M", "[a-z]", false),
            ("5", "[0-9]", true),
            ("-", "[a-]", true),
            ("b", "[a-]", false),
            ("]", "[]]", true),
            ("a", "[]a]", true),
            ("b", "[!]a]", true),
            ("]", "[!]a]", false),
            ("[", "[[]", true),
            ("[", "[[a]", true),
            ("a", "[[a]", true),
            ("^", "[^]", true),
            ("a", "[^]", false),
            ("^", r"[\^]", true),
            ("^", "[^a]", true),
            ("a", "[^a]", true),
            ("b", "[^a]", false),
            ("\\", r"[\]", true),
            ("&", "[&&]", true),
            ("a", "[a&&b]", true),
            ("~", "[~~]", true),
            ("|", "[|]", true),
            ("a-c", "a[-x]c", true),
            ("x", "a[-x]c", false),
            ("a", "[a-b-c]", true),
            ("-", "[a-b-c]", true),
            ("c", "[a-b-c]", true),
            ("b", "[a-b-c]", true),
            ("m", "[a-z-0]", true),
            ("0", "[a-z-0]", true),
            ("-", "[a-z-0]", true),
            ("a", "[a-a]", true),
            ("b", "[z-a]", false),
            ("a", "[z-a]", false),
            ("z", "[z-a]", false),
            ("a", "[b-a]x", false),
            ("-", "[-a]", true),
            ("a", "[-a]", true),
            ("b", "[-a]", false),
            ("-", "[!-a]", false),
            ("b", "[!-a]", true),
            ("a", "[!-a]", false),
            ("c", "[a-c-e]", true),
            ("d", "[a-c-e]", false),
            ("-", "[a-c-e]", true),
            ("e", "[a-c-e]", true),
            ("b", "[a-c-e]", true),
            ("f", "[a-c-e]", false),
            ("m", "[a-c-m-p]", true),
            ("-", "[a-c-m-p]", true),
            ("n", "[a-c-m-p]", true),
            ("q", "[a-c-m-p]", false),
            ("b", "[ab-]", true),
            ("-", "[ab-]", true),
            ("x", "[!a-c]", true),
            ("b", "[!a-c]", false),
            ("-", "[!a-]", false),
            ("z", "[!a-]", true),
            ("e", "[a-cx-z-e]", true),
            ("-", "[a-cx-z-e]", true),
            ("y", "[a-cx-z-e]", true),
            ("a", "[!]", false),
            ("-", "[!-a-c]", false),
            ("a", "[!-a-c]", false),
            ("b", "[!-a-c]", false),
            ("c", "[!-a-c]", false),
            ("d", "[!-a-c]", true),
            ("e", "[!-a-c]", true),
            ("f", "[!-a-c]", true),
            ("!", "[!-a-c]", true),
            ("]", "[!-a-c]", true),
            ("-", "[-a-c]", true),
            ("a", "[-a-c]", true),
            ("b", "[-a-c]", true),
            ("c", "[-a-c]", true),
            ("d", "[-a-c]", false),
            ("e", "[-a-c]", false),
            ("f", "[-a-c]", false),
            ("!", "[-a-c]", false),
            ("]", "[-a-c]", false),
            ("xy-", "xy[!-a-c]", false),
            ("xya", "xy[!-a-c]", false),
            ("xyb", "xy[!-a-c]", false),
            ("xyc", "xy[!-a-c]", false),
            ("xyd", "xy[!-a-c]", true),
            ("xye", "xy[!-a-c]", true),
            ("xyf", "xy[!-a-c]", true),
            ("xy!", "xy[!-a-c]", true),
            ("xy]", "xy[!-a-c]", true),
            ("xy-", "xy[-a-c]", true),
            ("xya", "xy[-a-c]", true),
            ("xyb", "xy[-a-c]", true),
            ("xyc", "xy[-a-c]", true),
            ("xyd", "xy[-a-c]", false),
            ("xye", "xy[-a-c]", false),
            ("xyf", "xy[-a-c]", false),
            ("xy!", "xy[-a-c]", false),
            ("xy]", "xy[-a-c]", false),
            ("xy-", "xy[a-c-]", true),
            ("xya", "xy[a-c-]", true),
            ("xyb", "xy[a-c-]", true),
            ("xyc", "xy[a-c-]", true),
            ("xyd", "xy[a-c-]", false),
            ("xye", "xy[a-c-]", false),
            ("xyf", "xy[a-c-]", false),
            ("xy!", "xy[a-c-]", false),
            ("xy]", "xy[a-c-]", false),
            ("xy-", "xy[!]a-c]", true),
            ("xya", "xy[!]a-c]", false),
            ("xyb", "xy[!]a-c]", false),
            ("xyc", "xy[!]a-c]", false),
            ("xyd", "xy[!]a-c]", true),
            ("xye", "xy[!]a-c]", true),
            ("xyf", "xy[!]a-c]", true),
            ("xy!", "xy[!]a-c]", true),
            ("xy]", "xy[!]a-c]", false),
            ("xy-", "xy[]a-c]", false),
            ("xya", "xy[]a-c]", true),
            ("xyb", "xy[]a-c]", true),
            ("xyc", "xy[]a-c]", true),
            ("xyd", "xy[]a-c]", false),
            ("xye", "xy[]a-c]", false),
            ("xyf", "xy[]a-c]", false),
            ("xy!", "xy[]a-c]", false),
            ("xy]", "xy[]a-c]", true),
            ("xy-", "xy[!a-c-e-g]", false),
            ("xya", "xy[!a-c-e-g]", false),
            ("xyb", "xy[!a-c-e-g]", false),
            ("xyc", "xy[!a-c-e-g]", false),
            ("xyd", "xy[!a-c-e-g]", true),
            ("xye", "xy[!a-c-e-g]", false),
            ("xyf", "xy[!a-c-e-g]", false),
            ("xy!", "xy[!a-c-e-g]", true),
            ("xy]", "xy[!a-c-e-g]", true),
            ("xy-", "xy[c-a-e]", true),
            ("xya", "xy[c-a-e]", false),
            ("xyb", "xy[c-a-e]", false),
            ("xyc", "xy[c-a-e]", false),
            ("xyd", "xy[c-a-e]", false),
            ("xye", "xy[c-a-e]", true),
            ("xyf", "xy[c-a-e]", false),
            ("xy!", "xy[c-a-e]", false),
            ("xy]", "xy[c-a-e]", false),
            ("!", "[!]", false),
            ("]", "[!]", false),
        ] {
            assert_eq!(case(name, pat), want, "{name:?} vs {pat:?}");
        }
    }

    #[test]
    fn an_unterminated_class_is_a_literal_bracket() {
        assert!(case("[", "["));
        assert!(case("x[", "x["));
        assert!(case("[abc", "[abc"));
        assert!(!case("a", "[abc"));
    }

    #[test]
    fn translate_wraps_in_a_full_match() {
        assert_eq!(translate("a*"), r"(?s)^(?:a.*)\z");
        assert_eq!(translate("**"), r"(?s)^(?:.*)\z");
        assert_eq!(translate("a?b"), r"(?s)^(?:a.b)\z");
    }

    #[test]
    fn cache_hands_back_the_same_regex() {
        let a = compiled("*.rs", false).unwrap();
        let b = compiled("*.rs", false).unwrap();
        assert!(Arc::ptr_eq(&a, &b));
        let c = compiled("*.rs", true).unwrap();
        assert!(c.is_match("X.RS") && !a.is_match("X.RS"));
    }

    #[test]
    fn the_cache_keeps_entries_below_its_cap_and_survives_passing_it() {
        let first = compiled("keep-one*", false).unwrap();
        let _second = compiled("keep-two*", false).unwrap();
        assert!(Arc::ptr_eq(&first, &compiled("keep-one*", false).unwrap()));
        for n in 0..4200 {
            assert!(compiled(&format!("fill{n}*"), false).is_some());
        }
        assert!(compiled("keep-one*", false).unwrap().is_match("keep-one!"));
    }

    #[test]
    fn cache_evicts_compiled_regexes_when_unique_patterns_exceed_the_cap() {
        let mut entries = Vec::new();
        for n in 0..4097 {
            let regex = compiled(&format!("bounded-{n}*"), false).unwrap();
            assert!(regex.is_match(&format!("bounded-{n}!")));
            entries.push(Arc::downgrade(&regex));
        }
        let retained = entries
            .iter()
            .filter(|entry| entry.strong_count() > 0)
            .count();
        assert!(retained <= 4096, "cache retained {retained} unique regexes");
        assert!(fnmatchcase("bounded-0!", "bounded-0*"));
        assert!(!fnmatchcase("different", "bounded-0*"));
    }

    #[test]
    fn host_fnmatch_follows_os_case_rules() {
        assert!(fnmatch("main.py", "*.py"));
        assert_eq!(fnmatch("MAIN.PY", "*.py"), cfg!(windows));
        assert_eq!(fnmatch("a/b", r"a\b"), cfg!(windows));
    }
}
