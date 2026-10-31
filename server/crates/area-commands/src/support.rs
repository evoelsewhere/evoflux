//! Discovery, request parsing and Starlette routing rules shared by the
//! `commands` and `snippets` lanes.
//!
//! Port of the helpers in app/services/commands.py that app/services/snippets.py
//! imports (`_iter_md`, `_parse_frontmatter`) and of the `_workspace_path`
//! helper in app/api/routes/commands.py.

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::io::Read;
use std::path::{Component, Path, PathBuf};

use axum::http::header::{ALLOW, CONTENT_TYPE, HOST, LOCATION};
use axum::http::{HeaderMap, HeaderValue, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use evoflux_core::ApiError;
use yaml_rust2::{Yaml, YamlLoader};

/// A discovered markdown file (a command or a snippet).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub name: String,
    pub description: String,
    pub body: String,
    pub source: &'static str,
}

/// Python's `str.strip()` and the regex `\s` class.
pub fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

pub fn py_strip(text: &str) -> &str {
    text.trim_matches(is_py_space)
}

/// `_FRONTMATTER_RE = ^---\s*\n(.*?)\n---\s*\n(.*)$` (DOTALL): the YAML block
/// and the text after the closing fence.
fn split_frontmatter(text: &str) -> Option<(&str, &str)> {
    let rest = text.strip_prefix("---")?;
    let lead = rest.find(|c| !is_py_space(c)).unwrap_or(rest.len());
    // `\s*` is greedy, so the opening `\n` is the last one of the whitespace run.
    // The regex only backtracks to the one before it when the closing fence
    // directly follows the run (`---\n\n---\nbody`); earlier ones add nothing.
    for (newline, _) in rest.get(..lead)?.rmatch_indices('\n').take(2) {
        let region = rest.get(newline + 1..)?;
        for (fence, _) in region.match_indices("\n---") {
            let tail = region.get(fence + 4..)?;
            let run = tail.find(|c| !is_py_space(c)).unwrap_or(tail.len());
            if let Some(close) = tail.get(..run)?.rfind('\n') {
                return Some((region.get(..fence)?, tail.get(close..)?.strip_prefix('\n')?));
            }
        }
    }
    None
}

/// The `description` of a YAML block as `yaml.safe_load` plus the
/// "only a string counts" rule would give it. Anything the parser rejects is
/// Python's uncaught `YAMLError`.
fn description_of(meta: &str) -> Result<String, ApiError> {
    let documents = YamlLoader::load_from_str(meta).map_err(|_| ApiError::internal())?;
    if documents.len() > 1 {
        return Err(ApiError::internal());
    }
    let Some(Yaml::Hash(map)) = documents.first() else {
        return Ok(String::new());
    };
    match map.get(&Yaml::String("description".to_owned())) {
        Some(Yaml::String(text)) => Ok(py_strip(text).to_owned()),
        _ => Ok(String::new()),
    }
}

/// `_parse_frontmatter` reduced to what callers use: the stripped
/// `description` and the body. `Err` is Python's uncaught YAML error (a 500).
pub fn parse_frontmatter(text: &str) -> Result<(String, String), ApiError> {
    match split_frontmatter(text) {
        None => Ok((String::new(), py_strip(text).to_owned())),
        Some((meta, body)) => Ok((description_of(meta)?, py_strip(body).to_owned())),
    }
}

fn markdown_stem(name: &str) -> Option<&str> {
    if name == ".md" {
        return Some(name);
    }
    name.strip_suffix(".md")
}

/// `_iter_md`: `(path, name)` for every `*.md` file at most one folder deep,
/// sorted by path. Folder symlinks are not followed, as `rglob` does not.
pub fn iter_md(root: &Path) -> Vec<(PathBuf, String)> {
    let mut found = Vec::new();
    let Ok(entries) = std::fs::read_dir(root) else {
        return found;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let file_name = entry.file_name().to_string_lossy().into_owned();
        let is_folder = entry.file_type().is_ok_and(|kind| kind.is_dir());
        if is_folder {
            let Ok(children) = std::fs::read_dir(&path) else {
                continue;
            };
            for child in children.flatten() {
                let child_path = child.path();
                let child_name = child.file_name().to_string_lossy().into_owned();
                if let Some(stem) = markdown_stem(&child_name) {
                    if child_path.is_file() {
                        found.push((child_path.clone(), format!("{file_name}/{stem}")));
                    }
                }
            }
        }
        if let Some(stem) = markdown_stem(&file_name) {
            if path.is_file() {
                found.push((path.clone(), stem.to_owned()));
            }
        }
    }
    found.sort();
    found
}

/// `read_text(encoding="utf-8")`: universal newlines, invalid UTF-8 is an
/// uncaught `UnicodeDecodeError`, and an unreadable file is skipped (`None`).
fn read_text(path: &Path) -> Option<Result<String, ApiError>> {
    let mut bytes = Vec::new();
    let mut file = std::fs::OpenOptions::new().read(true).open(path).ok()?;
    file.read_to_end(&mut bytes).ok()?;
    Some(
        String::from_utf8(bytes)
            .map(|text| text.replace("\r\n", "\n").replace('\r', "\n"))
            .map_err(|_| ApiError::internal()),
    )
}

/// First root wins on a name collision.
pub fn discover(roots: &[(PathBuf, &'static str)]) -> Result<BTreeMap<String, Entry>, ApiError> {
    let mut found = BTreeMap::new();
    for (root, source) in roots {
        for (path, name) in iter_md(root) {
            if found.contains_key(&name) {
                continue;
            }
            let Some(text) = read_text(&path) else {
                continue;
            };
            let (description, body) = parse_frontmatter(&text?)?;
            found.insert(
                name.clone(),
                Entry {
                    name,
                    description,
                    body,
                    source,
                },
            );
        }
    }
    Ok(found)
}

/// Percent-decoding as Starlette applies it to paths and query strings.
pub fn percent_decode(raw: &str, plus_is_space: bool) -> String {
    let digit = |byte: Option<u8>| byte.and_then(|b| char::from(b).to_digit(16));
    let mut rest = raw.bytes();
    let mut out = Vec::with_capacity(raw.len());
    while let Some(byte) = rest.next() {
        if byte == b'%' {
            let mut ahead = rest.clone();
            if let (Some(high), Some(low)) = (digit(ahead.next()), digit(ahead.next())) {
                out.push((high * 16 + low) as u8);
                rest = ahead;
                continue;
            }
        }
        out.push(if plus_is_space && byte == b'+' {
            b' '
        } else {
            byte
        });
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// The last value of `key`, as FastAPI reads a `str | None` query parameter.
pub fn query_last(query: Option<&str>, key: &str) -> Option<String> {
    let mut value = None;
    for pair in query?.split('&').filter(|pair| !pair.is_empty()) {
        let (name, raw) = pair.split_once('=').unwrap_or((pair, ""));
        if percent_decode(name, true) == key {
            value = Some(percent_decode(raw, true));
        }
    }
    value
}

/// Windows `canonicalize` returns `\\?\` paths; Python's `resolve()` does not.
fn strip_verbatim(path: PathBuf) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        return PathBuf::from(format!(r"\\{rest}"));
    }
    match text.strip_prefix(r"\\?\") {
        Some(rest) => PathBuf::from(rest),
        None => path,
    }
}

fn expand_user(raw: &str, home: &Path) -> PathBuf {
    if raw == "~" {
        return home.to_path_buf();
    }
    let rest = raw
        .strip_prefix("~/")
        .or_else(|| raw.strip_prefix("~\\").filter(|_| cfg!(windows)));
    match rest {
        Some(rest) => home.join(rest),
        None => PathBuf::from(raw),
    }
}

/// `Path(workspace).expanduser().resolve()`: absolute, `.`/`..` folded, and
/// the part that exists resolved through symlinks.
pub fn resolve_workspace(raw: &str, home: &Path, cwd: &Path) -> PathBuf {
    let expanded = expand_user(raw, home);
    let absolute = if expanded.is_absolute() {
        expanded
    } else {
        cwd.join(expanded)
    };
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                if normalized.file_name().is_some() {
                    normalized.pop();
                }
            }
            other => normalized.push(other.as_os_str()),
        }
    }
    let mut existing = normalized;
    let mut tail: Vec<OsString> = Vec::new();
    let mut base = loop {
        if let Ok(resolved) = existing.canonicalize() {
            break strip_verbatim(resolved);
        }
        match existing.file_name().map(OsString::from) {
            Some(name) => {
                tail.push(name);
                existing.pop();
            }
            None => break existing,
        }
    };
    for name in tail.into_iter().rev() {
        base.push(name);
    }
    base
}

pub fn workspace_error(path: &Path) -> ApiError {
    ApiError::new(
        StatusCode::UNPROCESSABLE_ENTITY,
        format!(
            "Workspace does not exist or is not a directory: {}",
            path.display()
        ),
    )
}

/// `_workspace_path` for a given `workspace` value: resolve it and require a folder.
pub async fn checked_workspace(raw: String, home: PathBuf) -> Result<PathBuf, ApiError> {
    evoflux_core::blocking::run(move || {
        let cwd = std::env::current_dir().unwrap_or_default();
        let path = resolve_workspace(&raw, &home, &cwd);
        if path.is_dir() {
            Ok(path)
        } else {
            Err(workspace_error(&path))
        }
    })
    .await?
}

/// A 200 response carrying already-serialized JSON.
pub fn json_ok(body: Result<Vec<u8>, serde_json::Error>) -> Result<Response, ApiError> {
    let body = body.map_err(|_| ApiError::internal())?;
    Ok(([(CONTENT_TYPE, "application/json")], body).into_response())
}

pub fn not_found() -> ApiError {
    ApiError::new(StatusCode::NOT_FOUND, "Not Found")
}

pub fn method_not_allowed(allow: &'static str) -> ApiError {
    let mut error = ApiError::new(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed");
    error.headers.insert(ALLOW, HeaderValue::from_static(allow));
    error
}

/// `redirect_slashes`: 307 to the same URL without the trailing slash.
pub fn redirect(headers: &HeaderMap, path: &str, query: Option<&str>) -> Response {
    let host = headers
        .get(HOST)
        .and_then(|value| value.to_str().ok())
        .unwrap_or("localhost");
    let query = query.map(|q| format!("?{q}")).unwrap_or_default();
    match HeaderValue::from_bytes(format!("http://{host}{path}{query}").as_bytes()) {
        Ok(location) => (StatusCode::TEMPORARY_REDIRECT, [(LOCATION, location)]).into_response(),
        Err(_) => ApiError::internal().into_response(),
    }
}

/// What Starlette's router does with a request path for one lane prefix.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Dispatch {
    List,
    Render(String),
    Redirect(String),
    MethodNotAllowed(&'static str),
    NotFound,
}

fn route_for(prefix: &str, path: &str) -> Option<Dispatch> {
    if path == prefix {
        return Some(Dispatch::List);
    }
    let rest = path.strip_prefix(prefix)?.strip_prefix('/')?;
    Some(Dispatch::Render(rest.strip_suffix("/render")?.to_owned()))
}

/// `GET prefix` and `POST prefix/{name:path}/render`; a path that only matches
/// without its trailing slash is redirected (`redirect_slashes`, 307).
pub fn dispatch(prefix: &str, decoded_path: &str, method: &Method) -> Dispatch {
    match route_for(prefix, decoded_path) {
        Some(Dispatch::List) if method != Method::GET => Dispatch::MethodNotAllowed("GET"),
        Some(Dispatch::Render(_)) if method != Method::POST => Dispatch::MethodNotAllowed("POST"),
        Some(route) => route,
        None => match decoded_path.strip_suffix('/') {
            Some(stripped) if route_for(prefix, stripped).is_some() => {
                Dispatch::Redirect(stripped.to_owned())
            }
            _ => Dispatch::NotFound,
        },
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    use std::fs;

    fn fm(text: &str) -> (String, String) {
        parse_frontmatter(text).unwrap_or_default()
    }

    #[test]
    fn description_cases() {
        let cases = [
            ("---\ndescription:   padded  \n---\nbody", "padded"),
            ("---\ndescription: 42\n---\nbody", ""),
            ("---\ndescription: [a, b]\n---\nbody", ""),
            ("---\ndescription:\n---\nbody", ""),
            ("---\nother: value\n---\nbody", ""),
            ("---\n---\nbody", ""),
            ("---\n- just\n- a list\n---\nbody", ""),
            ("---\njust a scalar\n---\nbody", ""),
            ("no frontmatter at all", ""),
            ("---\r\ndescription: crlf\r\n---\r\nbody", "crlf"),
            (
                "--- \ndescription: spaced fence\n---   \nbody",
                "spaced fence",
            ),
            (
                "---\ndescription: |\n  folded\n  text\n---\nbody",
                "folded\ntext",
            ),
        ];
        for (text, description) in cases {
            assert_eq!(fm(text).0, description, "{text:?}");
        }
    }

    #[test]
    fn body_cases() {
        let cases = [
            ("---\ndescription: d\n---\n\n  Body text  \n\n", "Body text"),
            ("plain\n\n", "plain"),
            ("---\ndescription: d\n---", "---\ndescription: d\n---"),
            ("---\ndescription: d\n---\n", ""),
            (
                "---\ndescription: d\n---\nline1\r\nline2\r\n",
                "line1\r\nline2",
            ),
            ("---\nA: 1\n---\nfirst\n---\nsecond", "first\n---\nsecond"),
            (
                "\n---\ndescription: d\n---\nbody",
                "---\ndescription: d\n---\nbody",
            ),
            ("", ""),
            ("---\n---\nbody", "---\n---\nbody"),
            ("---\n\n---\nbody", "body"),
            ("---\n \n \n---\nbody", "body"),
            ("---\n\n\n---\nbody", "body"),
            ("---\n\n\ndescription: x\n---\nbody", "body"),
            ("---\ndescription: d\n---  \n\n\nbody", "body"),
            (
                "---x\ndescription: d\n---\nbody",
                "---x\ndescription: d\n---\nbody",
            ),
        ];
        for (text, body) in cases {
            assert_eq!(fm(text).1, body, "{text:?}");
        }
    }

    #[test]
    fn frontmatter_yaml_errors_are_internal_errors() {
        let error = parse_frontmatter("---\na: [unclosed\n---\nbody").err();
        assert_eq!(error.map(|e| e.status.as_u16()), Some(500));
        let two_documents = parse_frontmatter("---\ndescription: d\n--- x\n---\nbody").err();
        assert_eq!(two_documents.map(|e| e.status.as_u16()), Some(500));
    }

    #[test]
    fn strip_follows_python_whitespace() {
        assert_eq!(py_strip(" \u{1c}\u{a0}x\u{2003}\n"), "x");
        assert!(is_py_space('\u{1f}'));
        assert!(!is_py_space('x'));
    }

    fn write(root: &Path, rel: &str, text: &str) {
        let path = root.join(rel);
        fs::create_dir_all(path.parent().unwrap_or(root)).unwrap_or_default();
        fs::write(path, text).unwrap_or_default();
    }

    #[test]
    fn iter_md_allows_one_level_of_nesting() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        write(root, "top.md", "x");
        write(root, "git/commit.md", "x");
        write(root, "git/deeper/too-deep.md", "x");
        write(root, "a/b/c/three.md", "x");
        write(root, "notes.txt", "x");
        write(root, "script.md.bak", "x");
        write(root, "release.notes.md", "x");
        write(root, "folder.md/inner.md", "x");
        let mut names: Vec<String> = iter_md(root).into_iter().map(|(_, n)| n).collect();
        names.sort();
        assert_eq!(
            names,
            ["folder.md/inner", "git/commit", "release.notes", "top"]
        );
        assert!(iter_md(&root.join("missing")).is_empty());
        assert!(iter_md(&root.join("top.md")).is_empty());
    }

    #[test]
    fn discover_first_root_wins_and_reads_utf8() {
        let dir = tempfile::tempdir().unwrap();
        let (a, b) = (dir.path().join("a"), dir.path().join("b"));
        write(&a, "x.md", "---\ndescription: from a\n---\nA\r\nline");
        write(&b, "x.md", "B");
        write(&b, "y.md", "Y");
        let found = discover(&[(a, "first"), (b, "second")]).unwrap();
        let names: Vec<_> = found.keys().cloned().collect();
        assert_eq!(names, ["x", "y"]);
        assert_eq!(found["x"].source, "first");
        assert_eq!(found["x"].description, "from a");
        assert_eq!(found["x"].body, "A\nline");
        assert_eq!(found["y"].source, "second");
    }

    #[test]
    fn discover_rejects_invalid_utf8_and_bad_yaml() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("r");
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("bad.md"), [0xff, 0xfe, 0x41]).unwrap();
        let error = discover(&[(root.clone(), "s")]).err();
        assert_eq!(error.map(|e| e.status.as_u16()), Some(500));
        fs::remove_file(root.join("bad.md")).unwrap();
        write(&root, "yaml.md", "---\na: [unclosed\n---\nbody");
        assert!(discover(&[(root, "s")]).is_err());
    }

    #[test]
    fn percent_decoding() {
        assert_eq!(percent_decode("a%2Fb%20c", false), "a/b c");
        assert_eq!(percent_decode("a+b", false), "a+b");
        assert_eq!(percent_decode("a+b%2B", true), "a b+");
        assert_eq!(percent_decode("%zz%4", false), "%zz%4");
        assert_eq!(percent_decode("%C3%A9", false), "é");
        assert_eq!(percent_decode("%FF", false), "\u{fffd}");
        assert_eq!(percent_decode("100%", false), "100%");
    }

    #[test]
    fn query_uses_the_last_value() {
        assert_eq!(query_last(None, "workspace"), None);
        assert_eq!(query_last(Some("a=1"), "workspace"), None);
        assert_eq!(
            query_last(Some("workspace=%2Fno&x=1&workspace=%2Fno2"), "workspace"),
            Some("/no2".to_owned())
        );
        assert_eq!(
            query_last(Some("workspace="), "workspace"),
            Some(String::new())
        );
        assert_eq!(
            query_last(Some("workspace"), "workspace"),
            Some(String::new())
        );
        assert_eq!(
            query_last(Some("workspace=a+b"), "workspace"),
            Some("a b".to_owned())
        );
        assert_eq!(
            query_last(Some("&&workspace=z"), "workspace"),
            Some("z".to_owned())
        );
        assert_eq!(query_last(Some("xworkspace=z"), "workspace"), None);
    }

    #[test]
    fn workspace_resolution() {
        let dir = tempfile::tempdir().unwrap();
        let base = dir.path().canonicalize().unwrap();
        let base = resolve_workspace(&base.to_string_lossy(), &base, &base);
        let home = base.join("home");
        let cwd = base.join("cwd");
        fs::create_dir_all(home.join("proj")).unwrap();
        fs::create_dir_all(&cwd).unwrap();
        assert_eq!(resolve_workspace("~", &home, &cwd), home);
        assert_eq!(resolve_workspace("~/proj", &home, &cwd), home.join("proj"));
        assert_eq!(resolve_workspace("", &home, &cwd), cwd);
        assert_eq!(resolve_workspace(".", &home, &cwd), cwd);
        assert_eq!(
            resolve_workspace("../home/proj", &home, &cwd),
            home.join("proj")
        );
        assert_eq!(
            resolve_workspace("missing/../other/x", &home, &cwd),
            cwd.join("other").join("x")
        );
        assert_eq!(resolve_workspace("~other", &home, &cwd), cwd.join("~other"));
        let absolute = home.join("proj");
        assert_eq!(
            resolve_workspace(&absolute.to_string_lossy(), &home, &cwd),
            absolute
        );
        let error = workspace_error(&absolute);
        assert_eq!(
            error.detail,
            format!(
                "Workspace does not exist or is not a directory: {}",
                absolute.display()
            )
        );
        assert_eq!(error.status.as_u16(), 422);
    }

    #[test]
    fn dispatch_matches_starlette() {
        let (get, post) = (Method::GET, Method::POST);
        let p = "/api/commands";
        assert_eq!(dispatch(p, "/api/commands", &get), Dispatch::List);
        assert_eq!(
            dispatch(p, "/api/commands", &post),
            Dispatch::MethodNotAllowed("GET")
        );
        assert_eq!(
            dispatch(p, "/api/commands/init/render", &post),
            Dispatch::Render("init".into())
        );
        assert_eq!(
            dispatch(p, "/api/commands/git/commit/render", &post),
            Dispatch::Render("git/commit".into())
        );
        assert_eq!(
            dispatch(p, "/api/commands//render", &post),
            Dispatch::Render(String::new())
        );
        assert_eq!(
            dispatch(p, "/api/commands/init/render", &get),
            Dispatch::MethodNotAllowed("POST")
        );
        assert_eq!(
            dispatch(p, "/api/commands/render", &post),
            Dispatch::NotFound
        );
        assert_eq!(dispatch(p, "/api/commands/init", &get), Dispatch::NotFound);
        assert_eq!(dispatch(p, "/api/commandsx", &get), Dispatch::NotFound);
        assert_eq!(
            dispatch(p, "/api/commands/", &get),
            Dispatch::Redirect("/api/commands".into())
        );
        assert_eq!(
            dispatch(p, "/api/commands/init/render/", &Method::DELETE),
            Dispatch::Redirect("/api/commands/init/render".into())
        );
        assert_eq!(
            dispatch(p, "/api/commands/render/", &post),
            Dispatch::NotFound
        );
        assert_eq!(dispatch(p, "/api/commands//", &get), Dispatch::NotFound);
        assert_eq!(dispatch(p, "/api/commands/x/", &get), Dispatch::NotFound);
    }
}
