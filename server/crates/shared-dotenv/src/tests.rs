//! Tests for the owner-accepted hardening of app/cli/seed.py and app/api/routes/mcp.py.
#![allow(clippy::unwrap_used, clippy::indexing_slicing)]

use super::*;

#[tokio::test]
async fn validation_rejects_invalid_names_without_touching_file_or_creating_parent() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(".env");
    tokio::fs::write(&path, b"OLD=keep\n").await.unwrap();
    for name in [
        "", "9KEY", "A-B", "A=B", "A B", "A\r", "A\nB", "A\0B", "é", "A!", "A/", "A@", "A[", "A`",
        "A{", "A:",
    ] {
        let result = merge_write(
            &path,
            &[("GOOD", "new"), (name, "sk-live-SECRET")],
            &WriteOpts::mcp(),
        )
        .await;
        assert!(
            matches!(result, Err(DotenvError::InvalidName)),
            "{name:?}: {result:?}"
        );
        assert_eq!(tokio::fs::read(&path).await.unwrap(), b"OLD=keep\n");
        let missing = dir.path().join("absent").join(".env");
        assert!(
            merge_write(&missing, &[(name, "x")], &WriteOpts::credentials(&[]))
                .await
                .is_err()
        );
        assert!(!missing.parent().unwrap().exists());
    }
}

#[tokio::test]
async fn validation_rejects_injected_values_without_leaking_them() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(".env");
    tokio::fs::write(&path, "OLD=keep\n").await.unwrap();
    for value in [
        "sk-live-SECRET\rOTHER=x",
        "sk-live-SECRET\nOTHER=x",
        "sk-live-SECRET\0",
    ] {
        for opts in [WriteOpts::credentials(&[]), WriteOpts::mcp()] {
            let error = merge_write(&path, &[("A", "ok"), ("KEY", value)], &opts)
                .await
                .unwrap_err();
            assert!(matches!(&error, DotenvError::InvalidValue { key } if key == "KEY"));
            assert!(!error.to_string().contains("sk-live-SECRET"));
            assert!(!format!("{error:?}").contains("sk-live-SECRET"));
            assert_eq!(tokio::fs::read(&path).await.unwrap(), b"OLD=keep\n");
            let missing = dir.path().join("absent").join(".env");
            assert!(merge_write(&missing, &[("KEY", value)], &opts)
                .await
                .is_err());
            assert!(!missing.parent().unwrap().exists());
        }
    }
}

/// Python `str.splitlines` boundaries, NUL, and CR LF together (SR-013).
const SEPARATORS: [&str; 12] = [
    "\n", "\r", "\r\n", "\u{b}", "\u{c}", "\u{1c}", "\u{1d}", "\u{1e}", "\u{85}", "\u{2028}",
    "\u{2029}", "\0",
];

#[tokio::test]
async fn validation_rejects_every_line_boundary_in_values_for_both_profiles() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(".env");
    tokio::fs::write(&path, "OLD=keep\n").await.unwrap();
    for sep in SEPARATORS {
        for value in [
            format!("sk-live-SECRET{sep}OPENAI_BASE_URL=http://evil.example"),
            format!("{sep}sk-live-SECRET"),
            format!("sk-live-SECRET{sep}"),
        ] {
            for opts in [WriteOpts::credentials(&[]), WriteOpts::mcp()] {
                let error = merge_write(&path, &[("A", "ok"), ("KEY", &value)], &opts)
                    .await
                    .unwrap_err();
                assert!(
                    matches!(&error, DotenvError::InvalidValue { key } if key == "KEY"),
                    "{sep:?}: {error:?}"
                );
                assert!(!error.to_string().contains("sk-live-SECRET"));
                assert!(!format!("{error:?}").contains("sk-live-SECRET"));
                assert_eq!(tokio::fs::read(&path).await.unwrap(), b"OLD=keep\n");
                let missing = dir.path().join("absent").join(".env");
                assert!(merge_write(&missing, &[("KEY", &value)], &opts)
                    .await
                    .is_err());
                assert!(!missing.parent().unwrap().exists());
            }
        }
    }
}

#[tokio::test]
async fn validation_rejects_every_line_boundary_in_names_for_both_profiles() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(".env");
    tokio::fs::write(&path, "OLD=keep\n").await.unwrap();
    for sep in SEPARATORS {
        for name in [
            format!("KEY{sep}OTHER"),
            format!("{sep}KEY"),
            format!("KEY{sep}"),
        ] {
            for opts in [WriteOpts::credentials(&[]), WriteOpts::mcp()] {
                let result = merge_write(&path, &[("A", "ok"), (&name, "x")], &opts).await;
                assert!(
                    matches!(result, Err(DotenvError::InvalidName)),
                    "{sep:?}: {result:?}"
                );
                assert_eq!(tokio::fs::read(&path).await.unwrap(), b"OLD=keep\n");
            }
        }
    }
}

#[tokio::test]
async fn refused_separator_cannot_inject_an_assignment_on_the_next_merge() {
    // The SR-013 PoC: a value with a separator, then any other merge.
    for sep in SEPARATORS {
        for mcp in [false, true] {
            let opts = if mcp {
                WriteOpts::mcp()
            } else {
                WriteOpts::credentials(&[])
            };
            let dir = tempfile::tempdir().unwrap();
            let path = dir.path().join(".env");
            let value = format!("sk-abc{sep}OPENAI_BASE_URL=http://evil.example");
            assert!(merge_write(&path, &[("OPENAI_API_KEY", &value)], &opts)
                .await
                .is_err());
            merge_write(&path, &[("OTHER", "1")], &opts).await.unwrap();
            let values = read(&path, &|_: &str| None).await.unwrap();
            assert!(!values.contains_key("OPENAI_BASE_URL"), "{sep:?}");
            assert!(!values.contains_key("OPENAI_API_KEY"), "{sep:?}");
            assert_eq!(values.get("OTHER"), Some(&Some("1".to_owned())));
        }
    }
}

#[tokio::test]
async fn values_with_other_control_and_unicode_characters_are_written() {
    // Not line boundaries for str.splitlines or python-dotenv: kept as is.
    for value in ["a\tb", "a\u{1f}b", "a\u{a0}b", "a\u{1b}b", "\u{7f}", "雪☃"] {
        for opts in [WriteOpts::credentials(&[]), WriteOpts::mcp()] {
            let dir = tempfile::tempdir().unwrap();
            let path = dir.path().join(".env");
            merge_write(&path, &[("KEY", value)], &opts).await.unwrap();
            let text = tokio::fs::read_to_string(&path).await.unwrap();
            assert!(text.contains(value), "{value:?}");
        }
    }
}

#[tokio::test]
async fn invalid_utf8_is_never_rewritten_and_errors_do_not_contain_contents() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(".env");
    let bytes = b"sk-live-SECRET\xff";
    tokio::fs::write(&path, bytes).await.unwrap();
    for opts in [WriteOpts::credentials(&[]), WriteOpts::mcp()] {
        let error = merge_write(&path, &[("A", "x")], &opts).await.unwrap_err();
        assert!(!error.to_string().contains("sk-live-SECRET"));
        assert_eq!(tokio::fs::read(&path).await.unwrap(), bytes);
    }
    assert!(read(&path, &|_| None).await.is_err());
}

#[tokio::test]
async fn missing_and_nonfile_reader_are_empty_like_python() {
    let dir = tempfile::tempdir().unwrap();
    assert!(read(&dir.path().join("missing"), &|_| None)
        .await
        .unwrap()
        .is_empty());
    assert!(read(dir.path(), &|_| None).await.unwrap().is_empty());
}

#[tokio::test]
async fn replacement_failure_cleans_temp_and_leaves_old_target() {
    // A live target handle denying delete deterministically fails atomic replace on Windows.
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(".env");
    #[cfg(windows)]
    {
        tokio::fs::write(&path, b"OLD=keep\n").await.unwrap();
        let _guard = tokio::fs::OpenOptions::new()
            .read(true)
            .share_mode(1)
            .open(&path)
            .await
            .unwrap();
        assert!(merge_write(&path, &[("A", "x")], &WriteOpts::mcp())
            .await
            .is_err());
        assert_eq!(tokio::fs::read(&path).await.unwrap(), b"OLD=keep\n");
    }
    #[cfg(not(windows))]
    {
        tokio::fs::create_dir(&path).await.unwrap();
        tokio::fs::write(path.join("old"), b"keep").await.unwrap();
        assert!(atomic_write(&path, "new".into()).await.is_err());
        assert_eq!(tokio::fs::read(path.join("old")).await.unwrap(), b"keep");
    }
    let mut entries = tokio::fs::read_dir(dir.path()).await.unwrap();
    assert_eq!(
        entries.next_entry().await.unwrap().unwrap().file_name(),
        ".env"
    );
    assert!(entries.next_entry().await.unwrap().is_none());
}

#[tokio::test]
async fn atomic_replace_changes_the_file_not_its_old_hard_link() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(".env");
    tokio::fs::write(&path, b"OLD=keep\n").await.unwrap();
    let snapshot = dir.path().join("snapshot");
    tokio::fs::hard_link(&path, &snapshot).await.unwrap();
    assert!(
        !merge_write(&path, &[("OLD", "changed")], &WriteOpts::mcp())
            .await
            .unwrap()
    );
    let bytes = tokio::fs::read(&snapshot).await.unwrap();
    assert_eq!(bytes, b"OLD=keep\n");
    assert_ne!(tokio::fs::read(&path).await.unwrap(), bytes);
}

#[cfg(unix)]
#[tokio::test]
async fn creates_and_replaces_with_owner_only_permissions() {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(".env");
    for opts in [WriteOpts::credentials(&[]), WriteOpts::mcp()] {
        merge_write(&path, &[("A", "x")], &opts).await.unwrap();
        assert_eq!(
            tokio::fs::metadata(&path)
                .await
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
        tokio::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))
            .await
            .unwrap();
    }
}

#[tokio::test]
async fn duplicate_update_names_use_last_value_in_first_position_like_python_dict() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(".env");
    merge_write(
        &path,
        &[("A", "first"), ("B", "second"), ("A", "last")],
        &WriteOpts::mcp(),
    )
    .await
    .unwrap();
    assert_eq!(
        tokio::fs::read_to_string(&path)
            .await
            .unwrap()
            .replace("\r\n", "\n"),
        "A=\"last\"\nB=\"second\"\n"
    );
}
