//! Request-builder contract of the pinned client (P-009 provider discovery and usage).
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
use evoflux_net::{pinned_client, Method, PinError, Policy, StatusCode};
use reqwest::dns::{Addrs, Name, Resolve, Resolving};
use std::net::{IpAddr, SocketAddr};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::task::JoinHandle;

const SECRET: &str = "sk-test-secret-value";

/// Answers `pinned.test` with 127.0.0.1 and every other name with `others`.
struct Answers {
    others: IpAddr,
    calls: Mutex<Vec<String>>,
}
impl Resolve for Answers {
    fn resolve(&self, name: Name) -> Resolving {
        let ip = if name.as_str() == "pinned.test" {
            "127.0.0.1".parse().unwrap()
        } else {
            self.others
        };
        self.calls.lock().unwrap().push(name.as_str().to_owned());
        Box::pin(async move { Ok(Box::new(std::iter::once(SocketAddr::new(ip, 0))) as Addrs) })
    }
}

struct Setup {
    policy: Policy,
    resolver: Arc<Answers>,
    cert: rcgen::CertifiedKey<rcgen::KeyPair>,
}

fn setup(others: &str, private: &[&str]) -> Setup {
    evoflux_net::install_crypto_provider();
    let cert = rcgen::generate_simple_self_signed(vec![
        "pinned.test".into(),
        "other.test".into(),
        "evil.test".into(),
    ])
    .unwrap();
    let resolver = Arc::new(Answers {
        others: others.parse().unwrap(),
        calls: Mutex::new(Vec::new()),
    });
    let mut policy = Policy {
        resolver: resolver.clone(),
        timeout: Duration::from_secs(5),
        ..Policy::default()
    };
    policy
        .root_certificates
        .push(reqwest::Certificate::from_der(cert.cert.der()).unwrap());
    policy
        .allow_private_hosts
        .extend(private.iter().map(|host| (*host).to_owned()));
    Setup {
        policy,
        resolver,
        cert,
    }
}

/// One captured request: lower-cased head plus raw body.
#[derive(Debug, Clone)]
struct Seen {
    head: String,
    body: Vec<u8>,
}
impl Seen {
    fn has(&self, header: &str) -> bool {
        self.head.lines().any(|line| {
            line.to_ascii_lowercase()
                .starts_with(&format!("{}:", header.to_ascii_lowercase()))
        })
    }
    fn line(&self) -> &str {
        self.head.lines().next().unwrap_or_default()
    }
}

async fn read_request<S: AsyncRead + Unpin>(stream: &mut S) -> Seen {
    let mut data = Vec::new();
    let mut buf = [0; 4096];
    let split = loop {
        if let Some(i) = data.windows(4).position(|s| s == b"\r\n\r\n") {
            break i + 4;
        }
        let n = stream.read(&mut buf).await.unwrap();
        assert!(n > 0, "connection closed mid-head");
        data.extend_from_slice(&buf[..n]);
    };
    let head = String::from_utf8(data[..split].to_vec()).unwrap();
    let length = head
        .lines()
        .find_map(|line| {
            let lower = line.to_ascii_lowercase();
            lower
                .strip_prefix("content-length:")
                .map(|v| v.trim().parse::<usize>().unwrap())
        })
        .unwrap_or(0);
    let mut body = data[split..].to_vec();
    while body.len() < length {
        let n = stream.read(&mut buf).await.unwrap();
        assert!(n > 0, "connection closed mid-body");
        body.extend_from_slice(&buf[..n]);
    }
    Seen { head, body }
}

async fn answer<S: AsyncRead + AsyncWrite + Unpin>(mut stream: S, response: Vec<u8>) -> Seen {
    let seen = read_request(&mut stream).await;
    stream.write_all(&response).await.unwrap();
    stream.shutdown().await.ok();
    seen
}

struct Server {
    listener: tokio::net::TcpListener,
    port: u16,
}

async fn bind() -> Server {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    Server { listener, port }
}

impl Server {
    fn url(&self, scheme: &str, host: &str, path: &str) -> String {
        format!("{scheme}://{host}:{}{path}", self.port)
    }

    /// Serve one connection per response over TLS, returning what each request carried.
    fn tls(self, setup: &Setup, responses: Vec<Vec<u8>>) -> JoinHandle<Vec<Seen>> {
        let config = rustls::ServerConfig::builder()
            .with_no_client_auth()
            .with_single_cert(
                vec![setup.cert.cert.der().clone()],
                rustls::pki_types::PrivatePkcs8KeyDer::from(setup.cert.signing_key.serialize_der())
                    .into(),
            )
            .unwrap();
        let acceptor = tokio_rustls::TlsAcceptor::from(Arc::new(config));
        tokio::spawn(async move {
            let mut seen = Vec::new();
            for response in responses {
                let (socket, _) = self.listener.accept().await.unwrap();
                let stream = acceptor.accept(socket).await.unwrap();
                seen.push(answer(stream, response).await);
            }
            seen
        })
    }

    fn plain(self, responses: Vec<Vec<u8>>) -> JoinHandle<Vec<Seen>> {
        tokio::spawn(async move {
            let mut seen = Vec::new();
            for response in responses {
                let (socket, _) = self.listener.accept().await.unwrap();
                seen.push(answer(socket, response).await);
            }
            seen
        })
    }
}

fn ok(body: &str) -> Vec<u8> {
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
    .into_bytes()
}

fn redirect(status: &str, location: &str) -> Vec<u8> {
    format!("HTTP/1.1 {status}\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        .into_bytes()
}

#[tokio::test]
async fn get_and_post_send_method_headers_and_json_body() {
    let s = setup("8.8.8.8", &["pinned.test"]);
    let server = bind().await;
    let base = server.url("https", "pinned.test", "/");
    let task = server.tls(&s, vec![ok(r#"{"data":[]}"#), ok(r#"{"ok":true}"#)]);
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();

    let response = client
        .request(Method::GET, &format!("{base}v1/models?api-version=1"))
        .header("Authorization", &format!("Bearer {SECRET}"))
        .header("x-api-key", SECRET)
        .public_header("anthropic-version", "2023-06-01")
        .timeout(Duration::from_secs(5))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status, StatusCode::OK);
    let value: serde_json::Value = response.json().unwrap();
    assert_eq!(value, serde_json::json!({"data": []}));
    assert_eq!(
        response.headers.get("content-type").unwrap(),
        "application/json"
    );

    let response = client
        .request(Method::POST, &format!("{base}api/show"))
        .json(&serde_json::json!({"model": "llama3"}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap();
    assert_eq!(response.body, br#"{"ok":true}"#);

    let seen = task.await.unwrap();
    assert_eq!(seen[0].line(), "GET /v1/models?api-version=1 HTTP/1.1");
    let head = seen[0].head.to_ascii_lowercase();
    assert!(head.contains(&format!("authorization: bearer {SECRET}")));
    assert!(head.contains(&format!("x-api-key: {SECRET}")));
    assert!(head.contains("anthropic-version: 2023-06-01"));
    assert!(!seen[0].has("content-type"));
    assert!(seen[0].body.is_empty());
    assert_eq!(seen[1].line(), "POST /api/show HTTP/1.1");
    assert!(seen[1]
        .head
        .to_ascii_lowercase()
        .contains("content-type: application/json"));
    assert_eq!(seen[1].body, br#"{"model":"llama3"}"#);
    // One resolution for the whole client: no rebinding window.
    assert_eq!(s.resolver.calls.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn credentials_are_dropped_on_a_cross_origin_redirect_and_kept_on_same_origin() {
    let s = setup("127.0.0.1", &["pinned.test", "other.test"]);
    let start = bind().await;
    let end = bind().await;
    let base = start.url("https", "pinned.test", "/");
    // Same host, same port: same origin; then a different port: another origin.
    let other = end.url("https", "pinned.test", "/landing");
    let start_task = start.tls(
        &s,
        vec![
            redirect("302 Found", "/again"),
            redirect("307 Temporary Redirect", &other),
        ],
    );
    let end_task = end.tls(&s, vec![ok("{}")]);
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    let response = client
        .request(Method::GET, &base)
        .header("Authorization", &format!("Bearer {SECRET}"))
        .header("X-Custom-Token", SECRET)
        .public_header("x-api-key", SECRET)
        .public_header("Accept", "application/json")
        .public_header("anthropic-version", "2023-06-01")
        .send()
        .await
        .unwrap();
    assert_eq!(response.status, StatusCode::OK);
    let first = start_task.await.unwrap();
    assert!(first[0].has("authorization") && first[0].has("x-custom-token"));
    assert!(first[0].has("x-api-key"));
    assert_eq!(first[1].line(), "GET /again HTTP/1.1");
    assert!(first[1].has("authorization") && first[1].has("x-api-key"));
    let landed = &end_task.await.unwrap()[0];
    assert_eq!(landed.line(), "GET /landing HTTP/1.1");
    assert!(!landed.head.contains(SECRET), "{}", landed.head);
    assert!(!landed.has("authorization") && !landed.has("x-api-key"));
    assert!(!landed.has("x-custom-token"));
    assert!(landed
        .head
        .to_ascii_lowercase()
        .contains("accept: application/json"));
    assert!(landed.has("anthropic-version"));
}

#[tokio::test]
async fn credentials_stay_dropped_after_returning_to_the_first_origin() {
    let s = setup("127.0.0.1", &["pinned.test", "other.test"]);
    let start = bind().await;
    let middle = bind().await;
    let base = start.url("https", "pinned.test", "/");
    let back = start.url("https", "pinned.test", "/back");
    let start_task = start.tls(
        &s,
        vec![
            redirect("302 Found", &middle.url("https", "other.test", "/")),
            ok("{}"),
        ],
    );
    let middle_task = middle.tls(&s, vec![redirect("302 Found", &back)]);
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    client
        .request(Method::GET, &base)
        .header("Authorization", SECRET)
        .send()
        .await
        .unwrap();
    let seen = start_task.await.unwrap();
    assert!(seen[0].has("authorization"));
    assert!(!seen[1].has("authorization"));
    assert!(!middle_task.await.unwrap()[0].has("authorization"));
}

#[tokio::test]
async fn post_redirects_follow_httpx_method_rules() {
    for (status, method, body) in [
        ("303 See Other", "GET", false),
        ("302 Found", "GET", false),
        ("301 Moved Permanently", "GET", false),
        ("307 Temporary Redirect", "POST", true),
        ("308 Permanent Redirect", "POST", true),
    ] {
        let s = setup("8.8.8.8", &["pinned.test"]);
        let server = bind().await;
        let base = server.url("https", "pinned.test", "/");
        let task = server.tls(&s, vec![redirect(status, "/next"), ok("{}")]);
        let client = pinned_client(&base, s.policy.clone()).await.unwrap();
        client
            .request(Method::POST, &base)
            .json(&serde_json::json!({"k": 1}))
            .send()
            .await
            .unwrap();
        let seen = task.await.unwrap();
        assert_eq!(seen[0].body, br#"{"k":1}"#);
        assert_eq!(
            seen[1].line(),
            format!("{method} /next HTTP/1.1"),
            "{status}"
        );
        assert_eq!(!seen[1].body.is_empty(), body, "{status}");
        assert_eq!(seen[1].has("content-type"), body, "{status}");
    }
}

#[tokio::test]
async fn a_303_turns_a_put_into_a_get_but_301_keeps_it() {
    for (status, method, body) in [
        ("303 See Other", "GET", false),
        ("301 Moved Permanently", "PUT", true),
    ] {
        let s = setup("8.8.8.8", &["pinned.test"]);
        let server = bind().await;
        let base = server.url("https", "pinned.test", "/");
        let task = server.tls(&s, vec![redirect(status, "/next"), ok("{}")]);
        let client = pinned_client(&base, s.policy.clone()).await.unwrap();
        client
            .request(Method::PUT, &base)
            .json(&serde_json::json!({}))
            .send()
            .await
            .unwrap();
        let seen = task.await.unwrap();
        assert_eq!(
            seen[1].line(),
            format!("{method} /next HTTP/1.1"),
            "{status}"
        );
        assert_eq!(!seen[1].body.is_empty(), body, "{status}");
    }
}

#[tokio::test]
async fn a_body_never_follows_a_cross_origin_307() {
    let s = setup("127.0.0.1", &["pinned.test"]);
    let start = bind().await;
    let other = bind().await;
    let base = start.url("https", "pinned.test", "/");
    let task = start.tls(
        &s,
        vec![redirect(
            "307 Temporary Redirect",
            &other.url("https", "pinned.test", "/"),
        )],
    );
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    let result = client
        .request(Method::POST, &base)
        .json(&serde_json::json!({"secret": SECRET}))
        .send()
        .await;
    assert!(matches!(result, Err(PinError::Redirect)));
    task.await.unwrap();
    drop(other);
}

#[tokio::test]
async fn redirect_to_a_private_or_rebound_address_is_refused() {
    // `evil.test` resolves (on the redirect hop) to loopback without an opt-in.
    for location in [
        "https://127.0.0.1/",
        "https://evil.test/",
        "https://localhost/",
    ] {
        let s = setup("127.0.0.2", &["pinned.test"]);
        let server = bind().await;
        let base = server.url("https", "pinned.test", "/");
        let task = server.tls(&s, vec![redirect("302 Found", location)]);
        let client = pinned_client(&base, s.policy.clone()).await.unwrap();
        let result = client
            .request(Method::GET, &base)
            .header("Authorization", SECRET)
            .send()
            .await;
        assert!(matches!(result, Err(PinError::Address)), "{location}");
        task.await.unwrap();
        let calls = s.resolver.calls.lock().unwrap().clone();
        let expected: &[&str] = if location == "https://evil.test/" {
            &["pinned.test", "evil.test"]
        } else {
            &["pinned.test"]
        };
        assert_eq!(calls, expected, "{location}");
    }
}

#[tokio::test]
async fn private_hosts_and_initial_origin_are_still_refused() {
    let s = setup("10.0.0.1", &[]);
    assert!(matches!(
        pinned_client("https://pinned.test/", s.policy.clone()).await,
        Err(PinError::Address)
    ));
    assert!(matches!(
        pinned_client("https://internal.test/", s.policy.clone()).await,
        Err(PinError::Address)
    ));
    let s = setup("8.8.8.8", &["pinned.test"]);
    let client = pinned_client("https://pinned.test/", s.policy.clone())
        .await
        .unwrap();
    for url in [
        "https://other.test/",
        "https://pinned.test:444/",
        "http://pinned.test/",
    ] {
        assert!(
            matches!(
                client.request(Method::GET, url).send().await,
                Err(PinError::Url)
            ),
            "{url}"
        );
    }
}

#[tokio::test]
async fn the_timeout_bounds_the_whole_exchange() {
    let s = setup("8.8.8.8", &["pinned.test"]);
    let server = bind().await;
    let base = server.url("https", "pinned.test", "/");
    // Accept and never answer.
    let silent = tokio::spawn(async move {
        let (socket, _) = server.listener.accept().await.unwrap();
        tokio::time::sleep(Duration::from_secs(3)).await;
        drop(socket);
    });
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    let started = std::time::Instant::now();
    let result = client
        .request(Method::GET, &base)
        .timeout(Duration::from_millis(200))
        .send()
        .await;
    assert!(matches!(result, Err(PinError::Timeout)));
    assert!(started.elapsed() < Duration::from_secs(2));
    silent.abort();
}

#[tokio::test]
async fn without_a_timeout_the_policy_bounds_each_hop() {
    let mut s = setup("8.8.8.8", &["pinned.test"]);
    s.policy.timeout = Duration::from_millis(200);
    let server = bind().await;
    let base = server.url("https", "pinned.test", "/");
    let silent = tokio::spawn(async move {
        let (socket, _) = server.listener.accept().await.unwrap();
        tokio::time::sleep(Duration::from_secs(3)).await;
        drop(socket);
    });
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    let result = client.request(Method::GET, &base).send().await;
    assert!(matches!(result, Err(PinError::Http(ref e)) if e.is_timeout()));
    silent.abort();
}

#[tokio::test]
async fn error_statuses_are_returned_with_their_capped_body() {
    let s = setup("8.8.8.8", &["pinned.test"]);
    let server = bind().await;
    let base = server.url("https", "pinned.test", "/");
    let task = server.tls(
        &s,
        vec![
            b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 6\r\nConnection: close\r\n\r\ndenied"
                .to_vec(),
            ok("toolong"),
            ok("1234"),
        ],
    );
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    let response = client.request(Method::GET, &base).send().await.unwrap();
    assert_eq!(response.status, StatusCode::UNAUTHORIZED);
    assert_eq!(response.body, b"denied");
    assert!(matches!(response.error_for_status(), Err(PinError::Status)));
    let result = client.request(Method::GET, &base).limit(4).send().await;
    assert!(matches!(result, Err(PinError::Size)));
    let response = client
        .request(Method::GET, &base)
        .limit(4)
        .send()
        .await
        .unwrap();
    assert_eq!(response.body, b"1234");
    assert!(matches!(response.json::<Vec<u8>>(), Err(PinError::Json)));
    task.await.unwrap();
}

#[tokio::test]
async fn invalid_headers_fail_without_sending_or_echoing_the_value() {
    let s = setup("8.8.8.8", &["pinned.test"]);
    let client = pinned_client("https://pinned.test/", s.policy.clone())
        .await
        .unwrap();
    let value = format!("{SECRET}\r\nInjected: yes");
    for request in [
        client
            .request(Method::GET, "https://pinned.test/")
            .header("Authorization", &value),
        client
            .request(Method::GET, "https://pinned.test/")
            .public_header("Accept", &value),
        client
            .request(Method::GET, "https://pinned.test/")
            .header("bad name", SECRET),
    ] {
        let error = request.send().await.err().unwrap();
        assert!(matches!(error, PinError::Header));
        assert!(!format!("{error} {error:?}").contains(SECRET));
    }
    struct Unserializable;
    impl serde::Serialize for Unserializable {
        fn serialize<S: serde::Serializer>(&self, _: S) -> Result<S::Ok, S::Error> {
            Err(serde::ser::Error::custom("no"))
        }
    }
    let result = client
        .request(Method::POST, "https://pinned.test/")
        .json(&Unserializable)
        .send()
        .await;
    assert!(matches!(result, Err(PinError::Body)));
}

#[tokio::test]
async fn plain_http_is_only_for_explicitly_allowed_hosts() {
    let mut s = setup("127.0.0.1", &["pinned.test", "other.test"]);
    let server = bind().await;
    let base = server.url("http", "pinned.test", "/");
    assert!(matches!(
        pinned_client(&base, s.policy.clone()).await,
        Err(PinError::Url)
    ));
    s.policy.allow_http_hosts.insert("pinned.test".into());
    let other = server.url("http", "other.test", "/");
    let task = server.plain(vec![ok(r#"{"models":[]}"#), redirect("302 Found", &other)]);
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    let response = client
        .request(Method::GET, &format!("{base}api/tags"))
        .send()
        .await
        .unwrap();
    assert_eq!(response.body, br#"{"models":[]}"#);
    // A redirect to a host without the opt-in may not use plain HTTP.
    assert!(matches!(
        client.request(Method::GET, &base).send().await,
        Err(PinError::Url)
    ));
    let seen = task.await.unwrap();
    assert_eq!(seen[0].line(), "GET /api/tags HTTP/1.1");
}

#[tokio::test]
async fn plain_http_opt_in_does_not_lift_the_address_checks() {
    let mut s = setup("127.0.0.1", &[]);
    s.policy.allow_http_hosts.insert("pinned.test".into());
    assert!(matches!(
        pinned_client("http://pinned.test:11434/", s.policy.clone()).await,
        Err(PinError::Address)
    ));
}

#[tokio::test]
async fn redirect_limit_applies_to_requests() {
    let mut s = setup("8.8.8.8", &["pinned.test"]);
    s.policy.max_redirects = 1;
    let server = bind().await;
    let base = server.url("https", "pinned.test", "/");
    let task = server.tls(
        &s,
        vec![redirect("302 Found", "/a"), redirect("302 Found", "/b")],
    );
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    assert!(matches!(
        client.request(Method::GET, &base).send().await,
        Err(PinError::Redirect)
    ));
    task.await.unwrap();
}

#[tokio::test]
async fn fetch_still_refuses_error_statuses() {
    let s = setup("8.8.8.8", &["pinned.test"]);
    let server = bind().await;
    let base = server.url("https", "pinned.test", "/");
    let task = server.tls(
        &s,
        vec![b"HTTP/1.1 500 Oops\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec()],
    );
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    assert!(matches!(
        client.fetch(&base, 10).await,
        Err(PinError::Http(_))
    ));
    let seen = task.await.unwrap();
    assert!(seen[0]
        .head
        .to_ascii_lowercase()
        .contains("accept: application/json, application/octet-stream"));
}

#[tokio::test]
async fn the_default_response_cap_is_eight_mebibytes() {
    assert_eq!(evoflux_net::DEFAULT_RESPONSE_LIMIT, 8_388_608);
    let s = setup("8.8.8.8", &["pinned.test"]);
    let server = bind().await;
    let base = server.url("https", "pinned.test", "/");
    let task = server.tls(
        &s,
        vec![b"HTTP/1.1 200 OK
Content-Length: 8388609
Connection: close

"
        .to_vec()],
    );
    let client = pinned_client(&base, s.policy.clone()).await.unwrap();
    assert!(matches!(
        client.request(Method::GET, &base).send().await,
        Err(PinError::Size)
    ));
    task.await.unwrap();
}
