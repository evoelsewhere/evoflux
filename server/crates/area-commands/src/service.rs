//! Port of app/services/commands.py (roots, rendering, built-ins) and of the
//! request-body validation FastAPI does for `CommandRenderRequest`.

use std::path::{Path, PathBuf};

use axum::http::StatusCode;
use evoflux_core::ApiError;
use serde_json::{json, Value};

use crate::builtin::INIT_BODY;
use crate::pyjson;
use crate::support::{py_strip, Entry};

/// Where discovery looks, in precedence order (`_candidate_roots`).
pub fn candidate_roots(
    workspace: Option<&Path>,
    config_dir: &Path,
    home: &Path,
) -> Vec<(PathBuf, &'static str)> {
    let mut roots = Vec::new();
    if let Some(workspace) = workspace {
        roots.push((
            workspace.join(".evoflux").join("commands"),
            "project-EvoFlux",
        ));
        roots.push((
            workspace.join(".opencode").join("commands"),
            "project-opencode",
        ));
    }
    roots.push((config_dir.join("commands"), "global-EvoFlux"));
    roots.push((
        home.join(".config").join("opencode").join("commands"),
        "global-opencode",
    ));
    roots
}

/// `get_builtin_command`.
pub fn builtin_command(name: &str) -> Option<Entry> {
    (name == "init").then(|| Entry {
        name: "init".to_owned(),
        description: "Create or update AGENTS.md for this project.".to_owned(),
        body: INIT_BODY.to_owned(),
        source: "builtin",
    })
}

/// `render_command`.
pub fn render_command(body: &str, arguments: &str) -> String {
    let arguments = py_strip(arguments);
    if body.contains("$ARGUMENTS") {
        return body.replace("$ARGUMENTS", arguments);
    }
    if arguments.is_empty() {
        return body.to_owned();
    }
    format!("{body}\n\n{arguments}")
}

fn invalid(entry: Value) -> ApiError {
    ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, Value::Array(vec![entry]))
}

/// FastAPI parses the body as JSON only for `application/json` and
/// `application/*+json`; anything else reaches pydantic as raw text.
fn is_json(content_type: Option<&str>) -> bool {
    let Some(content_type) = content_type else {
        return false;
    };
    let media = content_type.split(';').next().unwrap_or_default();
    match media.trim().to_ascii_lowercase().split_once('/') {
        Some(("application", subtype)) => subtype == "json" || subtype.ends_with("+json"),
        _ => false,
    }
}

/// Validate the render request body; returns `arguments`.
pub fn parse_render_body(content_type: Option<&str>, bytes: &[u8]) -> Result<String, ApiError> {
    if bytes.is_empty() {
        return Err(invalid(json!({
            "type": "missing", "loc": ["body"], "msg": "Field required", "input": null,
        })));
    }
    let body = if is_json(content_type) {
        let text = std::str::from_utf8(bytes).map_err(|_| {
            ApiError::new(
                StatusCode::BAD_REQUEST,
                "There was an error parsing the body",
            )
        })?;
        serde_json::from_str::<Value>(text).map_err(|_| {
            let (position, error) = pyjson::first_error(text).unwrap_or((0, "Expecting value"));
            invalid(json!({
                "type": "json_invalid", "loc": ["body", position], "msg": "JSON decode error",
                "input": {}, "ctx": {"error": error},
            }))
        })?
    } else {
        Value::String(String::from_utf8_lossy(bytes).into_owned())
    };
    let Value::Object(fields) = body else {
        return Err(invalid(json!({
            "type": "model_attributes_type", "loc": ["body"],
            "msg": "Input should be a valid dictionary or object to extract fields from",
            "input": body,
        })));
    };
    match fields.get("arguments") {
        None => Ok(String::new()),
        Some(Value::String(arguments)) => Ok(arguments.clone()),
        Some(other) => Err(invalid(json!({
            "type": "string_type", "loc": ["body", "arguments"],
            "msg": "Input should be a valid string", "input": other,
        }))),
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
mod tests {
    use super::*;

    #[test]
    fn roots_follow_the_four_sources() {
        let ws = Path::new("w");
        let with = candidate_roots(Some(ws), Path::new("cfg"), Path::new("home"));
        assert_eq!(
            with,
            vec![
                (
                    Path::new("w/.evoflux/commands").to_path_buf(),
                    "project-EvoFlux"
                ),
                (
                    Path::new("w/.opencode/commands").to_path_buf(),
                    "project-opencode"
                ),
                (Path::new("cfg/commands").to_path_buf(), "global-EvoFlux"),
                (
                    Path::new("home/.config/opencode/commands").to_path_buf(),
                    "global-opencode"
                ),
            ]
        );
        let without = candidate_roots(None, Path::new("cfg"), Path::new("home"));
        assert_eq!(without.len(), 2);
        assert_eq!(without[0].1, "global-EvoFlux");
    }

    #[test]
    fn builtin_init_only() {
        let init = builtin_command("init").unwrap();
        assert_eq!(init.name, "init");
        assert_eq!(
            init.description,
            "Create or update AGENTS.md for this project."
        );
        assert_eq!(init.source, "builtin");
        assert!(init.body.starts_with("Inspect the project at the current"));
        assert!(init.body.ends_with("instead of changing code."));
        assert!(builtin_command("Init").is_none());
        assert!(builtin_command("other").is_none());
    }

    #[test]
    fn builtin_init_keeps_the_v3_text_shape() {
        // The exact text is pinned by contract-tests/commands/snapshots/init-render.json.
        let body = builtin_command("init").unwrap().body;
        assert_eq!(body.chars().count(), 1405);
        assert!(!body.contains('\r'));
        assert_eq!(body.lines().count(), 8);
        for step in 1..=6 {
            assert!(body.contains(&format!("\n{step}. ")), "step {step}");
        }
    }

    #[test]
    fn render_substitutes_or_appends() {
        assert_eq!(render_command("Hello $ARGUMENTS.", "Ada"), "Hello Ada.");
        assert_eq!(
            render_command("$ARGUMENTS and $ARGUMENTS", "  go  "),
            "go and go"
        );
        assert_eq!(render_command("[$ARGUMENTS]", "   "), "[]");
        assert_eq!(render_command("Do it.", " now "), "Do it.\n\nnow");
        assert_eq!(render_command("Do it.", ""), "Do it.");
        assert_eq!(render_command("Do it.", " \n "), "Do it.");
        assert_eq!(
            render_command("$1 $ARGUMENT ${ARGUMENTS}", "x"),
            "$1 $ARGUMENT ${ARGUMENTS}\n\nx"
        );
        assert_eq!(render_command("<$ARGUMENTS>", "$ARGUMENTS"), "<$ARGUMENTS>");
    }

    fn detail(result: Result<String, ApiError>) -> Value {
        let error = result.unwrap_err();
        assert_eq!(error.status.as_u16(), 422);
        error.detail
    }

    #[test]
    fn body_accepts_objects() {
        let json = Some("application/json");
        assert_eq!(
            parse_render_body(json, br#"{"arguments":"a b"}"#).unwrap(),
            "a b"
        );
        assert_eq!(parse_render_body(json, b"{}").unwrap(), "");
        assert_eq!(
            parse_render_body(json, br#"{"arguments":"","x":1}"#).unwrap(),
            ""
        );
        assert_eq!(
            parse_render_body(
                Some("Application/Vnd.X+JSON; charset=utf-8"),
                br#"{"arguments":"a"}"#
            )
            .unwrap(),
            "a"
        );
    }

    #[test]
    fn body_missing() {
        let expected =
            json!([{"type":"missing","loc":["body"],"msg":"Field required","input":null}]);
        assert_eq!(
            detail(parse_render_body(Some("application/json"), b"")),
            expected
        );
        assert_eq!(detail(parse_render_body(None, b"")), expected);
    }

    #[test]
    fn body_wrong_shapes() {
        let json = Some("application/json");
        let not_object = |input: Value| {
            json!([{"type":"model_attributes_type","loc":["body"],
                "msg":"Input should be a valid dictionary or object to extract fields from",
                "input":input}])
        };
        assert_eq!(
            detail(parse_render_body(json, b"[]")),
            not_object(json!([]))
        );
        assert_eq!(
            detail(parse_render_body(json, br#""s""#)),
            not_object(json!("s"))
        );
        assert_eq!(
            detail(parse_render_body(None, b"{}")),
            not_object(json!("{}"))
        );
        assert_eq!(
            detail(parse_render_body(Some("text/plain"), b"{}")),
            not_object(json!("{}"))
        );
        assert_eq!(
            detail(parse_render_body(
                Some("application/x-www-form-urlencoded"),
                b"a=1"
            )),
            not_object(json!("a=1"))
        );
        for (body, input) in [
            (&br#"{"arguments":5}"#[..], json!(5)),
            (br#"{"arguments":null}"#, Value::Null),
            (br#"{"arguments":["a"]}"#, json!(["a"])),
            (br#"{"arguments":1.5}"#, json!(1.5)),
        ] {
            assert_eq!(
                detail(parse_render_body(json, body)),
                json!([{"type":"string_type","loc":["body","arguments"],
                    "msg":"Input should be a valid string","input":input}])
            );
        }
    }

    #[test]
    fn body_that_is_not_utf8_json_is_a_400() {
        let error = parse_render_body(Some("application/json"), &[0x7b, 0xff, 0x7d]).unwrap_err();
        assert_eq!(error.status.as_u16(), 400);
        assert_eq!(error.detail, "There was an error parsing the body");
    }

    #[test]
    fn body_json_errors() {
        let json = Some("application/json");
        for (body, position, error) in [
            (
                &b"{not json"[..],
                1,
                "Expecting property name enclosed in double quotes",
            ),
            (b"{\"a\" 1}", 5, "Expecting ':' delimiter"),
            (b"{\"a\":1 \"b\":2}", 7, "Expecting ',' delimiter"),
            (b"[1 2]", 3, "Expecting ',' delimiter"),
            (b"{} x", 3, "Extra data"),
            (b"[,]", 1, "Expecting value"),
            (b"{\"a\":\"b", 5, "Unterminated string starting at"),
            (b"\"a\nb\"", 2, "Invalid control character at"),
            (b"\"\\q\"", 1, "Invalid \\escape"),
            (b"NaN", 0, "Expecting value"),
        ] {
            let value = detail(parse_render_body(json, body));
            let entry = &value[0];
            assert_eq!(entry["type"], "json_invalid", "{body:?}");
            assert_eq!(entry["msg"], "JSON decode error");
            assert_eq!(entry["input"], json!({}));
            assert_eq!(entry["loc"], json!(["body", position]), "{body:?}");
            assert_eq!(entry["ctx"], json!({"error": error}), "{body:?}");
        }
    }
}
