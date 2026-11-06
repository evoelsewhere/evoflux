mod support;

use evo_office::manifest::Asset;
use evo_office::Runtime;
use support::*;

fn good(extra: Vec<Member<'static>>) -> Vec<u8> {
    let mut members = vec![
        Member::Dir("soffice/"),
        Member::Dir("soffice/program/"),
        Member::File("soffice/program/soffice.exe", b"binary", 0o755),
    ];
    members.extend(extra);
    archive(&members)
}

async fn install(
    bytes: &[u8],
    mutate: impl FnOnce(&mut Asset),
) -> (tempfile::TempDir, Runtime, Option<String>) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("a.tar.gz");
    std::fs::write(&path, bytes).unwrap();
    let mut asset = asset(file_url(&path), bytes, "soffice/program/soffice.exe");
    mutate(&mut asset);
    let runtime = Runtime::with_asset(&dir.path().join("runtimes"), Some(asset));
    runtime.start_install().unwrap();
    let error = finish(&runtime).await;
    (dir, runtime, error)
}

#[tokio::test]
async fn a_good_archive_installs_and_is_reported() {
    let (_dir, runtime, error) = install(&good(vec![]), |_| {}).await;
    assert_eq!(error, None);
    let installed = runtime.installed().expect("installed");
    assert_eq!(installed.version, "1.0");
    assert!(installed.executable.is_file());
    let status = runtime.status();
    assert_eq!(status.installed_version.as_deref(), Some("1.0"));
    assert!(status.job.is_none());
    // The partial download and the staging folder are gone.
    let leftovers = std::fs::read_dir(runtime.home())
        .unwrap()
        .flatten()
        .filter(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            name.starts_with(".download-") || name.starts_with(".staging-")
        })
        .count();
    assert_eq!(leftovers, 0);
    runtime.uninstall().unwrap();
    assert!(runtime.installed().is_none());
}

#[tokio::test]
async fn a_wrong_checksum_is_refused_and_nothing_is_activated() {
    let (_dir, runtime, error) = install(&good(vec![]), |a| a.sha256 = "0".repeat(64)).await;
    assert!(error.unwrap().contains("checksum"));
    assert!(runtime.installed().is_none());
    runtime.dismiss_error();
    assert!(runtime.status().job.is_none());
}

#[tokio::test]
async fn a_wrong_size_is_refused() {
    let (_dir, runtime, error) = install(&good(vec![]), |a| a.size -= 1).await;
    assert!(error.unwrap().contains("larger than pinned"));
    assert!(runtime.installed().is_none());
    let (_dir, runtime, error) = install(&good(vec![]), |a| a.size += 1).await;
    assert!(error.unwrap().contains("expected"));
    assert!(runtime.installed().is_none());
}

#[tokio::test]
async fn hostile_archives_are_refused() {
    let cases: Vec<(&str, Vec<u8>)> = vec![
        (
            "traversal",
            good(vec![Member::RawName("soffice/../evil.txt", b"x")]),
        ),
        (
            "outside root",
            good(vec![Member::File("other/x", b"x", 0o644)]),
        ),
        ("absolute", good(vec![Member::RawName("/etc/passwd", b"x")])),
        (
            "link escape",
            good(vec![Member::Symlink("soffice/program/l", "../../outside")]),
        ),
        (
            "absolute link",
            good(vec![Member::Symlink("soffice/program/l", "/etc")]),
        ),
        (
            "special file",
            good(vec![Member::Fifo("soffice/program/pipe")]),
        ),
        (
            "duplicate",
            good(vec![Member::File(
                "soffice/program/SOFFICE.EXE",
                b"y",
                0o755,
            )]),
        ),
    ];
    for (label, bytes) in cases {
        let (_dir, runtime, error) = install(&bytes, |_| {}).await;
        assert!(error.is_some(), "{label} was accepted");
        assert!(runtime.installed().is_none(), "{label} was activated");
    }
}

#[tokio::test]
async fn an_archive_without_the_executable_is_refused() {
    let bytes = archive(&[Member::File("soffice/readme.txt", b"x", 0o644)]);
    let (_dir, runtime, error) = install(&bytes, |_| {}).await;
    assert!(error.unwrap().contains("missing"));
    assert!(runtime.installed().is_none());
}

#[tokio::test]
async fn a_newer_version_replaces_the_older_one() {
    let dir = tempfile::tempdir().unwrap();
    let mut last = None;
    for version in ["1.0", "2.0"] {
        let bytes = archive(&[Member::File(
            "soffice/program/soffice.exe",
            version.as_bytes(),
            0o755,
        )]);
        let path = dir.path().join(format!("{version}.tar.gz"));
        std::fs::write(&path, &bytes).unwrap();
        let mut a = asset(file_url(&path), &bytes, "soffice/program/soffice.exe");
        a.version = version.into();
        let runtime = Runtime::with_asset(&dir.path().join("runtimes"), Some(a));
        runtime.start_install().unwrap();
        assert_eq!(finish(&runtime).await, None);
        last = Some(runtime);
    }
    let runtime = last.unwrap();
    assert_eq!(runtime.installed().unwrap().version, "2.0");
    assert!(!runtime.home().join("1.0").exists());
}

#[tokio::test]
async fn an_unsupported_platform_cannot_install() {
    let dir = tempfile::tempdir().unwrap();
    let runtime = Runtime::with_asset(dir.path(), None);
    assert!(!runtime.status().available);
    assert!(runtime.start_install().is_err());
}
