#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use evoflux_gateway::record::scrub_request_body;

#[test]
fn request_body_redacts_secrets_and_personal_information() {
    let text =
        "Bearer abcdefghijklmnop sk-abcdefghijklmnopqrstuvwxyz alice@example.com /home/alice/file";
    let cleaned = scrub_request_body(text);
    assert_eq!(
        cleaned,
        "Bearer <token> <api-key> <email> /home/<user>/file"
    );
}

#[test]
fn oversized_body_is_only_hash_and_length() {
    use evoflux_gateway::record::RequestBodyCapture;
    let mut capture = RequestBodyCapture::default();
    capture.push(&vec![b'a'; 1_048_577]);
    let body = capture.finish();
    assert_eq!(body["length"], 1_048_577);
    assert_eq!(
        body["sha256"],
        "4a3f0c0c213adea174f9a3d4c13177315b588bdb2e9c1012d3d0bf0453ca0f6a"
    );
    assert!(body.get("text").is_none());
}

#[tokio::test]
async fn request_sequence_tracks_arrival_order() {
    let temp = tempfile::tempdir().unwrap();
    let recorder = evoflux_gateway::record::Recorder::new(temp.path());
    assert!(recorder.next_sequence().await < recorder.next_sequence().await);
}

#[tokio::test]
async fn sequence_continues_when_recording_is_reopened() {
    let temp = tempfile::tempdir().unwrap();
    tokio::fs::write(
        temp.path().join("traffic.jsonl"),
        "{\"seq\":8}\n{\"seq\":3}\n",
    )
    .await
    .unwrap();
    let recorder = evoflux_gateway::record::Recorder::new(temp.path());
    assert_eq!(recorder.next_sequence().await, 9);
}
