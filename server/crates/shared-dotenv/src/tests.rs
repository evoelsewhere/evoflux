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
