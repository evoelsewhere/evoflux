//! `ls`: list the immediate children of a directory (`ls.py`).

use async_trait::async_trait;
use serde_json::{json, Value};

use crate::args::{self, Field, Kind, Val};
use crate::fsutil::{exists, is_dir, is_file, size};
use crate::sandbox::Sandbox;
use crate::{definition, property, run_blocking, Tool, ToolCtx, ToolOutput};

pub(crate) struct LsTool;

const DESCRIPTION: &str =
    "List immediate children of a directory with type and size. Preferred over shell ls or dir.";

fn fields() -> Vec<Field> {
    vec![Field::optional("path", Kind::Str, Val::Str(".".into()))]
}

pub(crate) fn run(sandbox: &Sandbox, path: &str) -> Result<String, String> {
    let resolved = sandbox.validate_path(path)?;
    let rel = sandbox.display_path(&resolved);
    if !exists(&resolved) {
        return Err(format!("Directory not found: {rel}"));
    }
    if !is_dir(&resolved) {
        return Err(format!("Path is not a directory: {rel}"));
    }

    let mut entries: Vec<(bool, String, std::path::PathBuf)> = std::fs::read_dir(&resolved)
        .map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .map(|entry| {
            let path = entry.path();
            (
                is_file(&path),
                entry.file_name().to_string_lossy().into_owned(),
                path,
            )
        })
        .collect();
    // Directories first, then files, each by name.
    entries.sort_by(|a, b| (a.0, &a.1).cmp(&(b.0, &b.1)));

    let lines: Vec<String> = entries
        .iter()
        .map(|(file, name, path)| {
            let indicator = if is_dir(path) { "d" } else { "f" };
            if *file {
                format!("[{indicator}] {name}  ({} bytes)", size(path))
            } else {
                format!("[{indicator}] {name}/")
            }
        })
        .collect();
    if lines.is_empty() {
        Ok("(empty directory)".to_owned())
    } else {
        Ok(lines.join("\n"))
    }
}

#[async_trait]
impl Tool for LsTool {
    fn name(&self) -> &str {
        "ls"
    }

    fn spec(&self) -> Value {
        definition(
            "ls",
            DESCRIPTION,
            json!({"path": property(
                Some(json!(".")),
                "Directory path (default '.' = workspace root).",
                &[("type", json!("string"))],
            )}),
            &[],
        )
    }

    async fn call(&self, args: Value, ctx: &ToolCtx) -> ToolOutput {
        let parsed = match args::parse("ls", &fields(), &args) {
            Ok(parsed) => parsed,
            Err(message) => return ToolOutput::error(&message),
        };
        let root = ctx.workspace_root.clone();
        let path = parsed.str("path");
        run_blocking("ls", move || run(&Sandbox::new(&root), &path)).await
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
    use crate::testutil::{link_dir, workspace};

    #[test]
    fn directories_come_first_then_files_each_by_name() {
        let (_d, s) = workspace(&[
            ("b.txt", "12345"),
            ("a.txt", ""),
            ("zdir/x", ""),
            ("adir/x", ""),
            ("Z.txt", "1"),
        ]);
        assert_eq!(
            run(&s, ".").unwrap(),
            "[d] adir/\n[d] zdir/\n[f] Z.txt  (1 bytes)\n[f] a.txt  (0 bytes)\n[f] b.txt  (5 bytes)"
        );
    }

    #[test]
    fn an_empty_directory_says_so() {
        let (d, s) = workspace(&[]);
        std::fs::create_dir(d.path().join("empty")).unwrap();
        assert_eq!(run(&s, "empty").unwrap(), "(empty directory)");
    }

    #[test]
    fn errors_name_the_display_path() {
        let (_d, s) = workspace(&[("sub/f.txt", "")]);
        assert_eq!(run(&s, "nope").unwrap_err(), "Directory not found: nope");
        assert_eq!(
            run(&s, "sub/f.txt").unwrap_err(),
            "Path is not a directory: sub/f.txt"
        );
        assert!(run(&s, "..")
            .unwrap_err()
            .contains("outside the allowed sandbox roots"));
    }

    #[test]
    fn a_link_to_a_directory_inside_the_workspace_lists_as_a_directory() {
        let (d, s) = workspace(&[("real/f.txt", "")]);
        link_dir(&d.path().join("real"), &d.path().join("alias"));
        assert_eq!(run(&s, ".").unwrap(), "[d] alias/\n[d] real/");
    }

    #[tokio::test]
    async fn the_tool_defaults_to_the_workspace_root_and_reports_errors() {
        let (d, _s) = workspace(&[("a.txt", "xy")]);
        let ctx = ToolCtx {
            workspace_root: d.path().to_path_buf(),
            session_id: "s".into(),
        };
        let listed = LsTool.call(json!({}), &ctx).await;
        assert_eq!(
            listed,
            ToolOutput {
                content: "[f] a.txt  (2 bytes)".into(),
                is_error: false
            }
        );
        let failed = LsTool.call(json!({"path": "nope"}), &ctx).await;
        assert_eq!(
            failed,
            ToolOutput {
                content: "Error: Directory not found: nope".into(),
                is_error: true
            }
        );
        let invalid = LsTool.call(json!({"path": 3}), &ctx).await;
        assert!(invalid.is_error && invalid.content.contains("Input should be a valid string"));
        assert_eq!(LsTool.name(), "ls");
    }
}
