//! Port of app/plugin_platform/marketplaces.py::_fetch_bytes security contract.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
use evoflux_net::{pinned_client, PinError, Policy};
use reqwest::dns::{Addrs, Name, Resolve, Resolving};
use std::net::{IpAddr, SocketAddr};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

struct Answers {
    first: Vec<IpAddr>,
    calls: AtomicUsize,
}
impl Resolve for Answers {
    fn resolve(&self, _: Name) -> Resolving {
        let ips = if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
            self.first.clone()
        } else {
            vec!["127.0.0.2".parse().unwrap()]
        };
        Box::pin(
            async move { Ok(Box::new(ips.into_iter().map(|ip| SocketAddr::new(ip, 0))) as Addrs) },
        )
    }
}
fn policy(ips: &[&str]) -> (Policy, Arc<Answers>) {
    let resolver = Arc::new(Answers {
        first: ips.iter().map(|s| s.parse().unwrap()).collect(),
        calls: AtomicUsize::new(0),
    });
    (
        Policy {
            resolver: resolver.clone(),
            timeout: Duration::from_secs(2),
            ..Policy::default()
        },
        resolver,
    )
}
async fn tls(
    response: &'static [u8],
) -> (
    String,
    reqwest::Certificate,
    tokio::task::JoinHandle<(String, String)>,
) {
    evoflux_net::install_crypto_provider();
    let cert = rcgen::generate_simple_self_signed(vec!["pinned.test".into()]).unwrap();
    let root = reqwest::Certificate::from_der(cert.cert.der()).unwrap();
    let config = rustls::ServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(
            vec![cert.cert.der().clone()],
            rustls::pki_types::PrivatePkcs8KeyDer::from(cert.signing_key.serialize_der()).into(),
        )
        .unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!(
        "https://pinned.test:{}/",
        listener.local_addr().unwrap().port()
    );
    let task = tokio::spawn(async move {
        let (socket, _) = listener.accept().await.unwrap();
        let mut stream = tokio_rustls::TlsAcceptor::from(Arc::new(config))
            .accept(socket)
            .await
            .unwrap();
        let sni = stream.get_ref().1.server_name().unwrap().to_string();
        let mut request = Vec::new();
        loop {
            let mut buf = [0; 1024];
            let n = stream.read(&mut buf).await.unwrap();
            if n == 0 {
                break;
            }
            request.extend_from_slice(&buf[..n]);
            if request.windows(4).any(|s| s == b"\r\n\r\n") {
                break;
            }
        }
        stream.write_all(response).await.unwrap();
        (sni, String::from_utf8(request).unwrap())
    });
    (url, root, task)
}
#[tokio::test]
async fn rejects_every_special_address_and_mixed_answers() {
    for ip in [
        "0.0.0.0",
        "10.0.0.1",
        "127.0.0.1",
        "169.254.1.1",
        "169.254.169.254",
        "172.16.0.1",
        "192.168.0.1",
        "100.64.0.1",
        "192.0.2.1",
        "198.18.0.1",
        "198.51.100.1",
        "203.0.113.1",
        "224.0.0.1",
        "255.255.255.255",
        "::",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "2001:db8::1",
        "2002::1",
        "::ffff:127.0.0.1",
        "::ffff:8.8.8.8",
    ] {
        let (p, _) = policy(&[ip]);
        assert!(
            matches!(
                pinned_client("pinned.test", p).await,
                Err(PinError::Address)
            ),
            "{ip}"
        );
        let (p, _) = policy(&["8.8.8.8", ip]);
        assert!(
            matches!(
                pinned_client("pinned.test", p).await,
                Err(PinError::Address)
            ),
            "mixed {ip}"
        );
    }
    let (p, _) = policy(&[]);
    assert!(matches!(
        pinned_client("pinned.test", p).await,
        Err(PinError::Address)
    ));
    for ip in ["8.8.8.8", "2606:4700:4700::1111"] {
        let (p, _) = policy(&[ip]);
        assert!(pinned_client("pinned.test", p).await.is_ok());
    }
}
#[tokio::test]
async fn tls_keeps_original_sni_and_host_and_never_resolves_twice() {
    let (url, root, server) =
        tls(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello").await;
    let (mut p, resolver) = policy(&["127.0.0.1"]);
    p.allow_private_hosts.insert("pinned.test".into());
    p.root_certificates.push(root);
    let client = pinned_client(&url, p).await.unwrap();
    assert_eq!(client.fetch(&url, 5).await.unwrap(), b"hello");
    assert_eq!(resolver.calls.load(Ordering::SeqCst), 1);
    let (sni, request) = server.await.unwrap();
    assert_eq!(sni, "pinned.test");
    assert!(request.to_lowercase().contains(&format!(
        "host: pinned.test:{}",
        reqwest::Url::parse(&url).unwrap().port().unwrap()
    )));
}
#[tokio::test]
async fn redirects_to_private_addresses_and_plain_http_are_refused() {
    for response in [b"HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/\r\nContent-Length: 0\r\n\r\n".as_slice(), b"HTTP/1.1 307 Temporary Redirect\r\nLocation: http://pinned.test/\r\nContent-Length: 0\r\n\r\n".as_slice()] {
        let (url, root, server) = tls(response).await;
        let (mut p, _) = policy(&["127.0.0.1"]);
        p.allow_private_hosts.insert("pinned.test".into()); p.root_certificates.push(root);
        let client = pinned_client(&url, p).await.unwrap();
        assert!(matches!(client.fetch(&url, 10).await, Err(PinError::Address | PinError::Url)));
        server.await.unwrap();
    }
}
#[tokio::test]
async fn enforces_size_with_and_without_content_length() {
    for response in [
        b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello".as_slice(),
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n".as_slice(),
    ] {
        let (url, root, server) = tls(response).await;
        let (mut p, _) = policy(&["127.0.0.1"]);
        p.allow_private_hosts.insert("pinned.test".into());
        p.root_certificates.push(root);
        let client = pinned_client(&url, p).await.unwrap();
        assert!(matches!(client.fetch(&url, 4).await, Err(PinError::Size)));
        server.await.unwrap();
    }
}
#[tokio::test]
async fn rejects_bad_urls_and_private_literals_before_dns() {
    for url in [
        "http://example.com",
        "https://user:pass@example.com",
        "https://:pass@example.com",
        "https://user@example.com",
        "https://example.com/#fragment",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://[::ffff:8.8.8.8]/",
        "https://localhost/",
        "https://name.localhost/",
        "https://name.local/",
        "https://name.internal/",
        "https://example.com/\\foo",
        "https://[invalid]/",
    ] {
        let (p, r) = policy(&["8.8.8.8"]);
        assert!(pinned_client(url, p).await.is_err(), "{url}");
        assert_eq!(r.calls.load(Ordering::SeqCst), 0);
    }
    let (p, _) = policy(&["8.8.8.8"]);
    assert!(
        pinned_client(&format!("https://example.com/{}", "a".repeat(2049)), p)
            .await
            .is_err()
    );
    let (p, _) = policy(&["8.8.8.8"]);
    assert!(
        pinned_client(&format!("https://example.com/{}", "a".repeat(2028)), p)
            .await
            .is_ok()
    ); // exactly 2048 bytes
}

struct Local;
impl Resolve for Local {
    fn resolve(&self, _: Name) -> Resolving {
        Box::pin(async { Ok(Box::new(std::iter::once("127.0.0.1:0".parse().unwrap())) as Addrs) })
    }
}

#[tokio::test]
async fn follows_checked_redirects_and_stops_at_exact_hop_limit() {
    let (end, root, end_server) = tls(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok").await;
    let response = Box::leak(
        format!("HTTP/1.1 301 Moved\r\nLocation: {end}\r\nContent-Length: 0\r\n\r\n")
            .into_bytes()
            .into_boxed_slice(),
    );
    let (middle, root2, middle_server) = tls(response).await;
    let response = Box::leak(
        format!("HTTP/1.1 303 See Other\r\nLocation: {middle}\r\nContent-Length: 0\r\n\r\n")
            .into_bytes()
            .into_boxed_slice(),
    );
    let (start, root3, start_server) = tls(response).await;
    let mut p = Policy {
        resolver: Arc::new(Local),
        max_redirects: 2,
        ..Policy::default()
    };
    p.allow_private_hosts.insert("pinned.test".into());
    p.root_certificates.extend([root, root2, root3]);
    assert_eq!(
        pinned_client(&start, p)
            .await
            .unwrap()
            .fetch(&start, 2)
            .await
            .unwrap(),
        b"ok"
    );
    start_server.await.unwrap();
    middle_server.await.unwrap();
    end_server.await.unwrap();

    let (url, root, server) =
        tls(b"HTTP/1.1 308 Permanent Redirect\r\nLocation: /again\r\nContent-Length: 0\r\n\r\n")
            .await;
    let mut p = Policy {
        resolver: Arc::new(Local),
        max_redirects: 0,
        ..Policy::default()
    };
    p.allow_private_hosts.insert("pinned.test".into());
    p.root_certificates.push(root);
    assert!(matches!(
        pinned_client(&url, p).await.unwrap().fetch(&url, 2).await,
        Err(PinError::Redirect)
    ));
    server.await.unwrap();
}

#[tokio::test]
async fn rejects_missing_location_http_error_and_other_initial_origin() {
    for (response, redirect) in [
        (
            b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\n".as_slice(),
            true,
        ),
        (
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n".as_slice(),
            false,
        ),
    ] {
        let (url, root, server) = tls(response).await;
        let (mut p, _) = policy(&["127.0.0.1"]);
        p.allow_private_hosts.insert("pinned.test".into());
        p.root_certificates.push(root);
        let client = pinned_client(&url, p).await.unwrap();
        assert!(matches!(
            client.fetch("https://other.test/", 10).await,
            Err(PinError::Url)
        ));
        let result = client.fetch(&url, 10).await;
        if redirect {
            assert!(matches!(result, Err(PinError::Redirect)));
        } else {
            assert!(matches!(result, Err(PinError::Http(_))));
        }
        server.await.unwrap();
    }
}

#[tokio::test]
async fn chunked_exact_cap_empty_body_and_gzip_decoded_cap() {
    for (response, limit, expected) in [
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nhe\r\n3\r\nllo\r\n0\r\n\r\n".as_slice(), 5, Some(b"hello".as_slice())),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n".as_slice(), 0, Some(b"".as_slice())),
        (b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 25\r\n\r\n\x1f\x8b\x08\0\0\0\0\0\0\x03\xcb\x48\xcd\xc9\xc9\x07\0\x86\xa6\x10\x36\x05\0\0\0".as_slice(), 4, None),
    ] {
        let (url, root, server) = tls(response).await;
        let (mut p, _) = policy(&["127.0.0.1"]);
        p.allow_private_hosts.insert("pinned.test".into()); p.root_certificates.push(root);
        let result = pinned_client(&url, p).await.unwrap().fetch(&url, limit).await;
        if let Some(bytes) = expected { assert_eq!(result.unwrap(), bytes); }
        else { assert!(matches!(result, Err(PinError::Size))); }
        server.await.unwrap();
    }
}

#[tokio::test]
async fn mapped_ipv6_stays_forbidden_even_with_explicit_opt_in() {
    let (mut p, _) = policy(&["::ffff:127.0.0.1"]);
    p.allow_private_hosts.insert("pinned.test".into());
    assert!(matches!(
        pinned_client("pinned.test", p).await,
        Err(PinError::Address)
    ));
}

#[tokio::test]
async fn default_system_resolver_can_pin_an_explicitly_allowed_localhost() {
    let mut p = Policy::default();
    p.allow_private_hosts.insert("localhost".into());
    assert!(pinned_client("localhost", p).await.is_ok());
}

#[tokio::test]
async fn dotted_hostname_still_connects_to_its_pinned_address() {
    let (url, root, server) = tls(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok").await;
    let url = url.replace("pinned.test:", "pinned.test.:");
    let (mut p, r) = policy(&["127.0.0.1"]);
    p.allow_private_hosts.insert("pinned.test".into());
    p.root_certificates.push(root);
    assert_eq!(
        pinned_client(&url, p)
            .await
            .unwrap()
            .fetch(&url, 10)
            .await
            .unwrap(),
        b"ok"
    );
    assert_eq!(r.calls.load(Ordering::SeqCst), 1);
    server.await.unwrap();
}

#[tokio::test]
async fn unhandled_redirection_is_an_error_like_python() {
    let (url, root, server) = tls(b"HTTP/1.1 304 Not Modified\r\nContent-Length: 0\r\n\r\n").await;
    let (mut p, _) = policy(&["127.0.0.1"]);
    p.allow_private_hosts.insert("pinned.test".into());
    p.root_certificates.push(root);
    assert!(pinned_client(&url, p)
        .await
        .unwrap()
        .fetch(&url, 10)
        .await
        .is_err());
    server.await.unwrap();
}

#[tokio::test]
async fn redirect_counter_prevents_a_third_hop() {
    let (end, root, end_server) =
        tls(b"HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/\r\nContent-Length: 0\r\n\r\n")
            .await;
    let response = Box::leak(
        format!("HTTP/1.1 302 Found\r\nLocation: {end}\r\nContent-Length: 0\r\n\r\n")
            .into_bytes()
            .into_boxed_slice(),
    );
    let (middle, root2, middle_server) = tls(response).await;
    let response = Box::leak(
        format!("HTTP/1.1 302 Found\r\nLocation: {middle}\r\nContent-Length: 0\r\n\r\n")
            .into_bytes()
            .into_boxed_slice(),
    );
    let (start, root3, start_server) = tls(response).await;
    let mut p = Policy {
        resolver: Arc::new(Local),
        max_redirects: 2,
        ..Policy::default()
    };
    p.allow_private_hosts.insert("pinned.test".into());
    p.root_certificates.extend([root, root2, root3]);
    assert!(matches!(
        pinned_client(&start, p)
            .await
            .unwrap()
            .fetch(&start, 10)
            .await,
        Err(PinError::Redirect)
    ));
    start_server.await.unwrap();
    middle_server.await.unwrap();
    end_server.await.unwrap();
}

#[tokio::test]
async fn advertised_oversize_is_rejected_before_reading_and_smaller_body_is_allowed() {
    for (response, oversized) in [
        (
            b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n".as_slice(),
            true,
        ),
        (
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok".as_slice(),
            false,
        ),
    ] {
        let (url, root, server) = tls(response).await;
        let (mut p, _) = policy(&["127.0.0.1"]);
        p.allow_private_hosts.insert("pinned.test".into());
        p.root_certificates.push(root);
        let result = pinned_client(&url, p).await.unwrap().fetch(&url, 10).await;
        if oversized {
            assert!(matches!(result, Err(PinError::Size)));
        } else {
            assert_eq!(result.unwrap(), b"ok");
        }
        server.await.unwrap();
    }
}

#[tokio::test]
async fn certificates_must_be_trusted_and_match_the_url_hostname() {
    for wrong_host in [false, true] {
        let (url, root, server) = tls(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok").await;
        let (mut p, _) = policy(&["127.0.0.1"]);
        let url = if wrong_host {
            p.root_certificates.push(root);
            url.replace("pinned.test", "other.test")
        } else {
            url
        };
        p.allow_private_hosts
            .extend(["pinned.test".into(), "other.test".into()]);
        assert!(matches!(
            pinned_client(&url, p).await.unwrap().fetch(&url, 10).await,
            Err(PinError::Http(_))
        ));
        server.abort();
        let _ = server.await;
    }
}

#[tokio::test]
#[allow(clippy::disallowed_methods)]
async fn proxy_environment_cannot_redirect_pinned_connections() {
    const CHILD: &str = "EVOFLUX_PINNED_PROXY_TEST";
    if std::env::var_os(CHILD).is_none() {
        assert!(std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "proxy_environment_cannot_redirect_pinned_connections"
            ])
            .env(CHILD, "1")
            .env("HTTPS_PROXY", "http://127.0.0.1:9")
            .env("ALL_PROXY", "http://127.0.0.1:9")
            .env("NO_PROXY", "")
            .status()
            .unwrap()
            .success());
        return;
    }
    let (url, root, server) = tls(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok").await;
    let (mut p, _) = policy(&["127.0.0.1"]);
    p.allow_private_hosts.insert("pinned.test".into());
    p.root_certificates.push(root);
    assert_eq!(
        pinned_client(&url, p)
            .await
            .unwrap()
            .fetch(&url, 10)
            .await
            .unwrap(),
        b"ok"
    );
    server.await.unwrap();
}
