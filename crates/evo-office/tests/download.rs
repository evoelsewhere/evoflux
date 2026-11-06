mod support;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use evo_office::{Phase, Runtime};
use support::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

#[derive(Clone, Copy)]
enum Mode {
    /// Answer `Range` with 206.
    Honor,
    /// Always answer 200 with the whole body.
    Ignore,
    /// Send the headers and a first chunk, then never finish.
    Stall,
}

/// A one-file HTTP server; returns its URL and a counter of requests.
async fn serve(body: Vec<u8>, mode: Mode) -> (String, Arc<AtomicUsize>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}/a.tar.gz", listener.local_addr().unwrap());
    let hits = Arc::new(AtomicUsize::new(0));
    let counter = hits.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut socket, _)) = listener.accept().await else {
                return;
            };
            counter.fetch_add(1, Ordering::SeqCst);
            let body = body.clone();
            tokio::spawn(async move {
                let mut buffer = vec![0u8; 4096];
                let n = socket.read(&mut buffer).await.unwrap_or(0);
                let request = String::from_utf8_lossy(&buffer[..n]).to_lowercase();
                let start = request
                    .lines()
                    .find_map(|l| l.strip_prefix("range: bytes="))
                    .and_then(|r| r.trim_end_matches('-').parse::<usize>().ok())
                    .unwrap_or(0);
                match mode {
                    Mode::Stall => {
                        let head =
                            format!("HTTP/1.1 200 OK\r\ncontent-length: {}\r\n\r\n", body.len());
                        let _ = socket.write_all(head.as_bytes()).await;
                        let _ = socket.write_all(&body[..10]).await;
                        tokio::time::sleep(Duration::from_secs(60)).await;
                    }
                    Mode::Ignore => {
                        let head = format!(
                            "HTTP/1.1 200 OK\r\ncontent-length: {}\r\nconnection: close\r\n\r\n",
                            body.len()
                        );
                        let _ = socket.write_all(head.as_bytes()).await;
                        let _ = socket.write_all(&body).await;
                    }
                    Mode::Honor => {
                        let rest = &body[start..];
                        let head = format!(
                            "HTTP/1.1 206 Partial Content\r\ncontent-length: {}\r\ncontent-range: bytes {start}-{}/{}\r\nconnection: close\r\n\r\n",
                            rest.len(),
                            body.len() - 1,
                            body.len()
                        );
                        let _ = socket.write_all(head.as_bytes()).await;
                        let _ = socket.write_all(rest).await;
                    }
                }
                let _ = socket.shutdown().await;
            });
        }
    });
    (url, hits)
}

fn runtime_archive() -> Vec<u8> {
    // Incompressible-ish content so the archive has some size to split.
    let mut state = 0x9E37_79B9_7F4A_7C15u64;
    let filler: Vec<u8> = (0..200_000)
        .map(|_| {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            (state >> 24) as u8
        })
        .collect();
    archive(&[Member::File("soffice/program/soffice.exe", &filler, 0o755)])
}

#[tokio::test]
async fn a_partial_download_resumes_with_a_range_request() {
    let bytes = runtime_archive();
    let (url, hits) = serve(bytes.clone(), Mode::Honor).await;
    let dir = tempfile::tempdir().unwrap();
    let asset = asset(url, &bytes, "soffice/program/soffice.exe");
    let runtime = Runtime::with_asset(&dir.path().join("runtimes"), Some(asset.clone()));
    // A previous attempt left the first part behind.
    std::fs::create_dir_all(runtime.home()).unwrap();
    std::fs::write(
        runtime
            .home()
            .join(format!(".download-{}.part", asset.sha256)),
        &bytes[..50_000],
    )
    .unwrap();
    runtime.start_install().unwrap();
    assert_eq!(finish(&runtime).await, None);
    assert!(runtime.installed().is_some());
    assert_eq!(hits.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn a_server_that_ignores_range_restarts_the_download() {
    let bytes = runtime_archive();
    let (url, _) = serve(bytes.clone(), Mode::Ignore).await;
    let dir = tempfile::tempdir().unwrap();
    let asset = asset(url, &bytes, "soffice/program/soffice.exe");
    let runtime = Runtime::with_asset(&dir.path().join("runtimes"), Some(asset.clone()));
    std::fs::create_dir_all(runtime.home()).unwrap();
    std::fs::write(
        runtime
            .home()
            .join(format!(".download-{}.part", asset.sha256)),
        &bytes[..50_000],
    )
    .unwrap();
    runtime.start_install().unwrap();
    assert_eq!(finish(&runtime).await, None);
    assert!(runtime.installed().is_some());
}

#[tokio::test]
async fn a_corrupt_partial_fails_on_the_checksum_and_is_discarded() {
    let bytes = runtime_archive();
    let (url, _) = serve(bytes.clone(), Mode::Honor).await;
    let dir = tempfile::tempdir().unwrap();
    let asset = asset(url, &bytes, "soffice/program/soffice.exe");
    let runtime = Runtime::with_asset(&dir.path().join("runtimes"), Some(asset.clone()));
    std::fs::create_dir_all(runtime.home()).unwrap();
    let part = runtime
        .home()
        .join(format!(".download-{}.part", asset.sha256));
    std::fs::write(&part, vec![7u8; 50_000]).unwrap();
    runtime.start_install().unwrap();
    assert!(finish(&runtime).await.unwrap().contains("checksum"));
    assert!(!part.exists());
    assert!(runtime.installed().is_none());
}

#[tokio::test]
async fn cancelling_a_download_discards_it() {
    let bytes = runtime_archive();
    let (url, _) = serve(bytes.clone(), Mode::Stall).await;
    let dir = tempfile::tempdir().unwrap();
    let asset = asset(url, &bytes, "soffice/program/soffice.exe");
    let runtime = Runtime::with_asset(&dir.path().join("runtimes"), Some(asset.clone()));
    runtime.start_install().unwrap();
    // Wait for the first bytes to arrive.
    for _ in 0..200 {
        if runtime.status().job.is_some_and(|j| j.bytes_done > 0) {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let job = runtime.status().job.unwrap();
    assert_eq!(job.phase, Phase::Downloading);
    assert!(job.bytes_done > 0 && job.bytes_total == bytes.len() as u64);
    runtime.cancel_install().unwrap();
    assert_eq!(finish(&runtime).await, None);
    assert!(!runtime
        .home()
        .join(format!(".download-{}.part", asset.sha256))
        .exists());
    // And uninstall works again once the task has ended.
    runtime.uninstall().unwrap();
}

#[tokio::test]
async fn a_failed_download_is_reported_and_can_be_dismissed() {
    let bytes = runtime_archive();
    let dir = tempfile::tempdir().unwrap();
    // Nothing listens on this port.
    let asset = asset(
        "http://127.0.0.1:9/a.tar.gz".into(),
        &bytes,
        "soffice/program/soffice.exe",
    );
    let runtime = Runtime::with_asset(&dir.path().join("runtimes"), Some(asset));
    runtime.start_install().unwrap();
    assert!(finish(&runtime).await.unwrap().contains("Download failed"));
    assert_eq!(runtime.status().job.unwrap().phase, Phase::Failed);
    runtime.dismiss_error();
    assert!(runtime.status().job.is_none());
}
