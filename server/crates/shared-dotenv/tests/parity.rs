//! Python golden fixtures: python-dotenv, app/cli/seed.py and app/api/routes/mcp.py.
#![forbid(unsafe_code)]
#![allow(clippy::unwrap_used, clippy::indexing_slicing)]

use evoflux_shared_dotenv::{merge_write, parse, read, WriteOpts};
use serde_json::Value;

fn pairs(value: &Value) -> Vec<(&str, &str)> {
    value
        .as_array()
        .unwrap()
        .iter()
        .map(|p| (p[0].as_str().unwrap(), p[1].as_str().unwrap()))
        .collect()
}

#[tokio::test]
async fn python_reader_fixtures_preserve_values_and_order() {
    let cases: Value = serde_json::from_str(include_str!("fixtures/read.json")).unwrap();
    assert!(cases.as_array().unwrap().len() >= 80);
    let dir = tempfile::tempdir().unwrap();
    for case in cases.as_array().unwrap() {
        let env = |key: &str| {
            case["env"]
                .get(key)
                .and_then(Value::as_str)
                .map(str::to_owned)
        };
        let text = case["text"].as_str().unwrap();
        let expected: Vec<(String, Option<String>)> =
            serde_json::from_value(case["expected"].clone()).unwrap();
        assert_eq!(
            parse(text, &env).into_iter().collect::<Vec<_>>(),
            expected,
            "{}",
            case["name"]
        );
        let path = dir.path().join(".env");
        tokio::fs::write(&path, text).await.unwrap();
        assert_eq!(
            read(&path, &env)
                .await
                .unwrap()
                .into_iter()
                .collect::<Vec<_>>(),
            expected,
            "{}",
            case["name"]
        );
    }
}

#[tokio::test]
async fn python_writer_fixtures_match_bytes_and_created_flag() {
    let cases: Value = serde_json::from_str(include_str!("fixtures/write.json")).unwrap();
    assert!(cases.as_array().unwrap().len() >= 40);
    for case in cases.as_array().unwrap() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nested").join(".env");
        if let Some(text) = case["existing"].as_str() {
            tokio::fs::create_dir_all(path.parent().unwrap())
                .await
                .unwrap();
            tokio::fs::write(&path, text).await.unwrap();
        }
        let comments = pairs(&case["comments"]);
        let opts = if case["mode"] == "credentials" {
            WriteOpts::credentials(&comments)
        } else {
            WriteOpts::mcp()
        };
        assert_eq!(
            merge_write(&path, &pairs(&case["updates"]), &opts)
                .await
                .unwrap(),
            case["created"].as_bool().unwrap(),
            "{}",
            case["name"]
        );
        let platform = if cfg!(windows) { "windows" } else { "unix" };
        if case["expected"][platform].is_null() {
            assert!(!path.exists());
            assert!(!path.parent().unwrap().exists());
        } else {
            let expected: Vec<u8> =
                serde_json::from_value(case["expected"][platform].clone()).unwrap();
            assert_eq!(
                tokio::fs::read(&path).await.unwrap(),
                expected,
                "{}",
                case["name"]
            );
            let mut entries = tokio::fs::read_dir(path.parent().unwrap()).await.unwrap();
            assert_eq!(
                entries.next_entry().await.unwrap().unwrap().file_name(),
                ".env"
            );
            assert!(entries.next_entry().await.unwrap().is_none());
        }
    }
}
