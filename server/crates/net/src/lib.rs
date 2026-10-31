//! The one shared HTTPS client of the v4 server (design: rust-http-client-and-stack-recheck).
//!
//! Every outbound HTTP call goes through [`build_client`]'s client, which units
//! receive through `UnitState`. It uses rustls with the aws-lc-rs provider and
//! the OS trust store, honours the environment and system proxy, and has connect
//! and read (idle) timeouts but no total timeout, so streaming responses can run
//! as long as bytes keep arriving. A total timeout is a per-request choice.

#![forbid(unsafe_code)]

use std::sync::Once;
use std::time::Duration;

pub use reqwest::Client;

pub const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
pub const READ_TIMEOUT: Duration = Duration::from_secs(60);

#[derive(Debug, thiserror::Error)]
#[error("cannot build the HTTPS client: {0}")]
pub struct BuildError(#[from] reqwest::Error);

/// The timeouts of the shared client; [`Timeouts::default`] is what production uses.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Timeouts {
    pub connect: Duration,
    /// Longest gap between two reads of a response; not a limit on the whole response.
    pub read: Duration,
}

impl Default for Timeouts {
    fn default() -> Self {
        Self {
            connect: CONNECT_TIMEOUT,
            read: READ_TIMEOUT,
        }
    }
}

/// Install the aws-lc-rs rustls provider as the process default, once.
pub fn install_crypto_provider() {
    static INSTALL: Once = Once::new();
    INSTALL.call_once(|| {
        // Err means another provider is already the default; that one stays.
        let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    });
}

pub fn build_client() -> Result<Client, BuildError> {
    build_client_with(Timeouts::default())
}

pub fn build_client_with(timeouts: Timeouts) -> Result<Client, BuildError> {
    install_crypto_provider();
    Ok(Client::builder()
        .connect_timeout(timeouts.connect)
        .read_timeout(timeouts.read)
        .build()?)
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::disallowed_methods)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::routing::get;
    use axum::Router;
    use std::convert::Infallible;
    use std::net::SocketAddr;

    async fn serve(app: Router) -> SocketAddr {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        addr
    }

    fn quick(read_ms: u64) -> Client {
        build_client_with(Timeouts {
            connect: Duration::from_secs(5),
            read: Duration::from_millis(read_ms),
        })
        .unwrap()
    }

    /// A body of `chunks` pieces, one every `gap_ms`, after `head_ms` of silence.
    fn slow(head_ms: u64, gap_ms: u64, chunks: u32) -> Router {
        Router::new().route(
            "/",
            get(move || async move {
                tokio::time::sleep(Duration::from_millis(head_ms)).await;
                let stream = futures_lite_stream(gap_ms, chunks);
                Body::from_stream(stream)
            }),
        )
    }

    fn futures_lite_stream(
        gap_ms: u64,
        chunks: u32,
    ) -> impl futures_core::Stream<Item = Result<&'static str, Infallible>> {
        futures_util::stream::unfold(0, move |sent| async move {
            if sent == chunks {
                return None;
            }
            tokio::time::sleep(Duration::from_millis(gap_ms)).await;
            Some((Ok("x"), sent + 1))
        })
    }

    #[test]
    fn defaults_are_the_documented_timeouts() {
        let defaults = Timeouts::default();
        assert_eq!(defaults.connect, Duration::from_secs(10));
        assert_eq!(defaults.read, Duration::from_secs(60));
    }

    #[test]
    fn installs_the_aws_lc_rs_provider_once() {
        install_crypto_provider();
        install_crypto_provider();
        assert!(rustls::crypto::CryptoProvider::get_default().is_some());
    }

    const FRESH: &str = "tests::building_the_client_installs_the_provider";

    /// Runs in a child process: other tests install the provider in this one.
    #[test]
    fn building_the_client_installs_the_provider() {
        if std::env::var_os("EVOFLUX_NET_FRESH_PROCESS").is_some() {
            assert!(rustls::crypto::CryptoProvider::get_default().is_none());
            build_client().unwrap();
            assert!(rustls::crypto::CryptoProvider::get_default().is_some());
            return;
        }
        let status = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", FRESH, "--test-threads=1"])
            .env("EVOFLUX_NET_FRESH_PROCESS", "1")
            .status()
            .unwrap();
        assert!(status.success());
    }

    #[tokio::test]
    async fn fetches_json_from_a_local_server() {
        let app = Router::new().route(
            "/q",
            get(|| async { axum::Json(serde_json::json!({"quote": "q"})) }),
        );
        let addr = serve(app).await;
        let value: serde_json::Value = build_client()
            .unwrap()
            .get(format!("http://{addr}/q"))
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        assert_eq!(value.get("quote").and_then(|v| v.as_str()), Some("q"));
    }

    #[tokio::test]
    async fn a_silent_server_trips_the_read_timeout() {
        let addr = serve(slow(1_000, 0, 1)).await;
        let error = quick(150)
            .get(format!("http://{addr}/"))
            .send()
            .await
            .unwrap_err();
        assert!(error.is_timeout(), "{error}");
    }

    #[tokio::test]
    async fn a_stalled_body_trips_the_read_timeout() {
        let addr = serve(slow(0, 1_000, 2)).await;
        let response = quick(150)
            .get(format!("http://{addr}/"))
            .send()
            .await
            .unwrap();
        let error = response.bytes().await.unwrap_err();
        assert!(error.is_timeout(), "{error}");
    }

    /// The whole response takes about 800 ms against a 300 ms read timeout:
    /// only a total timeout could stop it.
    #[tokio::test]
    async fn a_steady_stream_outlives_the_read_timeout() {
        let addr = serve(slow(0, 100, 8)).await;
        let body = quick(300)
            .get(format!("http://{addr}/"))
            .send()
            .await
            .unwrap()
            .text()
            .await
            .unwrap();
        assert_eq!(body, "xxxxxxxx");
    }

    #[tokio::test]
    async fn gzip_responses_are_decoded() {
        let app = Router::new().route(
            "/",
            get(|| async {
                (
                    [("content-encoding", "gzip")],
                    // gzip of "hello"
                    vec![
                        0x1f, 0x8b, 8, 0, 0, 0, 0, 0, 0, 3, 0xcb, 0x48, 0xcd, 0xc9, 0xc9, 7, 0,
                        0x86, 0xa6, 0x10, 0x36, 5, 0, 0, 0,
                    ],
                )
            }),
        );
        let addr = serve(app).await;
        let text = build_client()
            .unwrap()
            .get(format!("http://{addr}/"))
            .send()
            .await
            .unwrap()
            .text()
            .await
            .unwrap();
        assert_eq!(text, "hello");
    }
}
