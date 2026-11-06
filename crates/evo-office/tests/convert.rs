mod support;

use std::time::{Duration, Instant};

use evo_office::Error;
use support::*;

/// A stand-in for `soffice`: finds `--outdir <dir>` and writes `document.pdf` there.
#[cfg(windows)]
const CONVERTS: &str = "@echo off\r\nsetlocal\r\nset \"OUT=\"\r\n:l\r\nif \"%~1\"==\"\" goto done\r\nif \"%~1\"==\"--outdir\" set \"OUT=%~2\"\r\nshift\r\ngoto l\r\n:done\r\necho %%PDF-fake> \"%OUT%\\document.pdf\"\r\nexit /b 0\r\n";
#[cfg(not(windows))]
const CONVERTS: &str = "#!/bin/sh\nwhile [ $# -gt 0 ]; do [ \"$1\" = \"--outdir\" ] && OUT=\"$2\"; shift; done\necho '%PDF-fake' > \"$OUT/document.pdf\"\n";

/// Initialises its profile on the first run and exits without converting (as LibreOffice does).
#[cfg(windows)]
const FIRST_RUN_EXITS: &str = "@echo off\r\nif not exist \"%~dp0ran\" (\r\n  echo.> \"%~dp0ran\"\r\n  exit /b 0\r\n)\r\ncall \"%~dp0real.cmd\" %*\r\n";
#[cfg(not(windows))]
const FIRST_RUN_EXITS: &str = "#!/bin/sh\nif [ ! -f \"$(dirname \"$0\")/ran\" ]; then touch \"$(dirname \"$0\")/ran\"; exit 81; fi\nexec \"$(dirname \"$0\")/real.sh\" \"$@\"\n";

#[cfg(windows)]
const FAILS: &str = "@echo off\r\necho boom 1>&2\r\nexit /b 3\r\n";
#[cfg(not(windows))]
const FAILS: &str = "#!/bin/sh\necho boom >&2\nexit 3\n";

#[cfg(windows)]
const HANGS: &str = "@echo off\r\nping -n 60 127.0.0.1 > nul\r\n";
#[cfg(not(windows))]
const HANGS: &str = "#!/bin/sh\nsleep 60\n";

fn document(dir: &std::path::Path, name: &str) -> std::path::PathBuf {
    let path = dir.join(name);
    std::fs::write(&path, b"content").unwrap();
    path
}

#[tokio::test]
async fn a_document_becomes_a_pdf_and_the_original_is_untouched() {
    let dir = tempfile::tempdir().unwrap();
    let runtime = fake_runtime(dir.path(), CONVERTS).await;
    let source = document(dir.path(), "Quarterly report ünïcode.docx");
    let work = dir.path().join("work");
    let pdf = runtime
        .convert_to_pdf(&source, &work, Duration::from_secs(30))
        .await
        .unwrap();
    assert!(std::fs::read(&pdf).unwrap().starts_with(b"%PDF"));
    assert_eq!(std::fs::read(&source).unwrap(), b"content");
    // The hardened profile was written.
    let settings = std::fs::read_to_string(
        runtime
            .home()
            .join("profile/user/registrymodifications.xcu"),
    )
    .unwrap();
    assert!(settings.contains("DisableMacrosExecution"));
}

#[tokio::test]
async fn unsupported_files_and_a_missing_runtime_are_refused() {
    let dir = tempfile::tempdir().unwrap();
    let runtime = fake_runtime(dir.path(), CONVERTS).await;
    let source = document(dir.path(), "notes.txt");
    let error = runtime
        .convert_to_pdf(&source, &dir.path().join("w"), Duration::from_secs(5))
        .await
        .unwrap_err();
    assert!(matches!(error, Error::Convert(_)));

    let empty = evo_office::Runtime::with_asset(&dir.path().join("none"), None);
    let source = document(dir.path(), "a.docx");
    let error = empty
        .convert_to_pdf(&source, &dir.path().join("w2"), Duration::from_secs(5))
        .await
        .unwrap_err();
    assert!(matches!(error, Error::NotInstalled));
}

#[tokio::test]
async fn a_failing_conversion_reports_stderr() {
    let dir = tempfile::tempdir().unwrap();
    let runtime = fake_runtime(dir.path(), FAILS).await;
    let source = document(dir.path(), "a.xlsx");
    let error = runtime
        .convert_to_pdf(&source, &dir.path().join("w"), Duration::from_secs(30))
        .await
        .unwrap_err();
    assert!(error.to_string().contains("boom"), "{error}");
}

#[tokio::test]
async fn a_hang_is_killed_at_the_timeout() {
    let dir = tempfile::tempdir().unwrap();
    let runtime = fake_runtime(dir.path(), HANGS).await;
    let source = document(dir.path(), "a.pptx");
    let started = Instant::now();
    let error = runtime
        .convert_to_pdf(&source, &dir.path().join("w"), Duration::from_millis(800))
        .await
        .unwrap_err();
    assert!(matches!(error, Error::Timeout(_)), "{error}");
    assert!(started.elapsed() < Duration::from_secs(20));
}

#[tokio::test]
async fn a_first_run_that_only_initialises_the_profile_is_retried() {
    let dir = tempfile::tempdir().unwrap();
    // Install a wrapper as `soffice` next to the real fake.
    let (wrapper, real, mode) = if cfg!(windows) {
        ("soffice/fake.cmd", "soffice/real.cmd", 0o644)
    } else {
        ("soffice/fake.sh", "soffice/real.sh", 0o755)
    };
    let bytes = archive(&[
        Member::File(wrapper, FIRST_RUN_EXITS.as_bytes(), mode),
        Member::File(real, CONVERTS.as_bytes(), mode),
    ]);
    let path = dir.path().join("r.tar.gz");
    std::fs::write(&path, &bytes).unwrap();
    let runtime = evo_office::Runtime::with_asset(
        &dir.path().join("runtimes"),
        Some(asset(file_url(&path), &bytes, wrapper)),
    );
    runtime.start_install().unwrap();
    assert_eq!(finish(&runtime).await, None);
    let source = document(dir.path(), "a.docx");
    let pdf = runtime
        .convert_to_pdf(&source, &dir.path().join("w"), Duration::from_secs(30))
        .await
        .unwrap();
    assert!(pdf.is_file());
}

#[tokio::test]
async fn conversions_do_not_overlap() {
    let dir = tempfile::tempdir().unwrap();
    let runtime = fake_runtime(dir.path(), CONVERTS).await;
    let a = document(dir.path(), "a.docx");
    let b = document(dir.path(), "b.docx");
    let (w1, w2) = (dir.path().join("w1"), dir.path().join("w2"));
    let (first, second) = tokio::join!(
        runtime.convert_to_pdf(&a, &w1, Duration::from_secs(30)),
        runtime.convert_to_pdf(&b, &w2, Duration::from_secs(30)),
    );
    assert!(first.is_ok() && second.is_ok());
}
