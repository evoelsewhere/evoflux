//! Ticket regressions through the model-facing Tool::call boundary.
#![allow(clippy::unwrap_used, clippy::disallowed_methods)]
use evoflux_area_tools::{read_only_tools, ToolCtx};
use serde_json::json;

#[tokio::test]
async fn saved_policy_reaches_every_available_file_tool() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    std::fs::create_dir_all(root.join("secrets")).unwrap();
    std::fs::write(root.join("secret.txt"), "hidden payload").unwrap();
    std::fs::write(root.join("ok.txt"), "public payload").unwrap();
    let ctx = ToolCtx {
        workspace_root: root,
        session_id: "policy".into(),
        denied_patterns: vec!["**/secret*".into()],
    };
    for tool in read_only_tools() {
        let args = match tool.name() {
            "read" => json!({"path": "secret.txt"}),
            "ls" => json!({"path": "secrets"}),
            "glob" => json!({"directory": "secrets", "pattern": "*"}),
            "grep" => json!({"directory": "secrets", "pattern": "payload"}),
            _ => continue,
        };
        let out = tool.call(args, &ctx).await;
        assert!(out.is_error, "{}: {out:?}", tool.name());
        assert!(
            out.content
                .ends_with("is inside a denied sandbox root: **/secret*"),
            "{out:?}"
        );
        if tool.name() == "glob" {
            for mode in ["path", "name"] {
                let out = tool
                    .call(json!({"pattern":"*.txt", "match": mode}), &ctx)
                    .await;
                assert!(!out.is_error);
                assert_eq!(out.content, "ok.txt");
            }
        }
        if tool.name() == "grep" {
            let out = tool.call(json!({"pattern":"payload"}), &ctx).await;
            assert!(!out.is_error);
            assert_eq!(out.content, "ok.txt:1: public payload");
        }
    }
}
