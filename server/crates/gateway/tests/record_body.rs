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
fn request_body_redacts_each_rule() {
    let key = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----";
    let cases = [
        (key.to_owned(), "<private-key>".to_owned()),
        (format!("ghp_{}", "a".repeat(36)), "<api-key>".to_owned()),
        (
            format!("github_pat_{}", "A1_".repeat(12)),
            "<api-key>".to_owned(),
        ),
        ("AKIAABCDEFGHIJKLMNOP".to_owned(), "<api-key>".to_owned()),
        (format!("AIza{}", "b".repeat(35)), "<api-key>".to_owned()),
        ("xoxb-1234567890-abcdef".to_owned(), "<api-key>".to_owned()),
        (
            "/x?_token=secret123&a=1".to_owned(),
            "/x?_token=<token>&a=1".to_owned(),
        ),
        (
            "/x?%5Ftoken=secret123".to_owned(),
            "/x?%5Ftoken=<token>".to_owned(),
        ),
        (
            r"C:\Users\alice\repo".to_owned(),
            r"C:\Users\<user>\repo".to_owned(),
        ),
        (
            "/Users/alice/repo".to_owned(),
            "/Users/<user>/repo".to_owned(),
        ),
    ];
    for (input, expected) in cases {
        assert_eq!(scrub_request_body(&input), expected, "input: {input}");
    }
}

#[test]
fn json_values_of_sensitive_keys_are_redacted() {
    let cleaned = scrub_request_body(
        r#"{"user":"bob","Password":"hunter2","nested":{"api_key":"short","list":[{"Authorization":"x"}]},"cookie":{"a":1},"n":1}"#,
    );
    let value: serde_json::Value = serde_json::from_str(&cleaned).unwrap();
    assert_eq!(value["user"], "bob");
    assert_eq!(value["n"], 1);
    assert_eq!(value["Password"], "<removed>");
    assert_eq!(value["nested"]["api_key"], "<removed>");
    assert_eq!(value["nested"]["list"][0]["Authorization"], "<removed>");
    assert_eq!(value["cookie"], "<removed>");
    assert!(!cleaned.contains("hunter2"));
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
