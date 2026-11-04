//! Port of app/plugin_platform/marketplaces.py::_fetch_bytes; pins DNS to close rebinding.
//! The request builder serves the provider calls of app/agent/providers/model_discovery.py
//! and app/agent/providers/{codex,copilot,opencode}/usage.py (P-009).

use ipnet::IpNet;
use reqwest::dns::{Addrs, Name, Resolve, Resolving};
use reqwest::header::{HeaderMap, HeaderName, HeaderValue, CONTENT_TYPE};
use reqwest::{Client, Method, StatusCode, Url};
use std::collections::HashSet;
use std::net::{IpAddr, SocketAddr};
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, thiserror::Error)]
pub enum PinError {
    #[error("download requires a valid HTTPS URL without credentials or a fragment")]
    Url,
    #[error("download host must resolve only to allowed addresses")]
    Address,
    #[error("download host could not be resolved")]
    Dns,
    #[error("download deadline exceeded")]
    Timeout,
    #[error("download returned an invalid redirect or exceeded its redirect limit")]
    Redirect,
    #[error("download response exceeds its size limit")]
    Size,
    #[error("download returned an unsuccessful status")]
    Status,
    #[error("HTTPS download failed")]
    Http(#[from] reqwest::Error),
    /// A caller header name or value is invalid; the value is never included.
    #[error("request header is invalid")]
    Header,
    #[error("request body could not be encoded as JSON")]
    Body,
    #[error("response body is not the expected JSON")]
    Json,
}

/// Private opt-in names are normalized hostnames, without brackets or a port.
/// Opt-in never transfers to a different redirect host. Mapped IPv6 is forbidden.
#[derive(Clone)]
pub struct Policy {
    pub allow_private_hosts: HashSet<String>,
    /// Normalized hostnames that may also be reached over plain HTTP (local
    /// daemons such as Ollama, mock providers). Every other host is HTTPS only,
    /// including redirect targets; address checks still apply.
    pub allow_http_hosts: HashSet<String>,
    pub resolver: Arc<dyn Resolve>,
    /// Bounds DNS and each complete request, including the response body.
    pub timeout: Duration,
    pub max_redirects: usize,
    pub root_certificates: Vec<reqwest::Certificate>,
}

impl Default for Policy {
    fn default() -> Self {
        Self {
            allow_private_hosts: HashSet::new(),
            allow_http_hosts: HashSet::new(),
            resolver: Arc::new(SystemResolver),
            timeout: Duration::from_secs(30),
            max_redirects: 3,
            root_certificates: Vec::new(),
        }
    }
}

pub struct SystemResolver;
impl Resolve for SystemResolver {
    fn resolve(&self, name: Name) -> Resolving {
        Box::pin(async move {
            let addresses = tokio::net::lookup_host((name.as_str(), 0)).await?;
            let addresses: Vec<_> = addresses.collect();
            Ok(Box::new(addresses.into_iter()) as Addrs)
        })
    }
}

// Fail closed if reqwest ever tries to resolve a name not explicitly pinned.
struct NoDns;
impl Resolve for NoDns {
    fn resolve(&self, _: Name) -> Resolving {
        Box::pin(async { Err(std::io::Error::other("unpinned hostname").into()) })
    }
}

pub struct PinnedClient {
    origin: Url,
    client: Client,
    policy: Policy,
}

/// Resolve once, reject every disallowed answer, and bind HTTPS to those addresses.
/// `host` is a hostname/authority or an HTTPS URL; fetches must start at its origin.
pub async fn pinned_client(host: &str, policy: Policy) -> Result<PinnedClient, PinError> {
    let origin = if host.contains("://") {
        parse_url(host, &policy)?
    } else {
        parse_url(&format!("https://{host}/"), &policy)?
    };
    let client = pin(&origin, &policy).await?;
    Ok(PinnedClient {
        origin,
        client,
        policy,
    })
}

fn parse_url(value: &str, policy: &Policy) -> Result<Url, PinError> {
    if value.len() > 2048 || value.contains('\\') {
        return Err(PinError::Url);
    }
    let url = Url::parse(value).map_err(|_| PinError::Url)?;
    let scheme_allowed = match url.scheme() {
        "https" => true,
        "http" => plain_http_allowed(&url, policy),
        _ => false,
    };
    if !scheme_allowed
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err(PinError::Url);
    }
    Ok(url)
}

fn plain_http_allowed(url: &Url, policy: &Policy) -> bool {
    hostname(url).is_ok_and(|host| policy.allow_http_hosts.contains(&host))
}

fn hostname(url: &Url) -> Result<String, PinError> {
    Ok(url
        .host_str()
        .ok_or(PinError::Url)?
        .trim_start_matches('[')
        .trim_end_matches(']')
        .trim_end_matches('.')
        .to_ascii_lowercase())
}

fn public(ip: IpAddr) -> bool {
    // Conservative special-use exclusions. No mapped/transition IPv6 addresses:
    // they can route into IPv4 private networks despite looking globally scoped.
    const DENIED: &[&str] = &[
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/3",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "3fff::/20",
    ];
    if ip.is_ipv6() {
        // Currently allocated global unicast is 2000::/3; fails closed for all
        // local, multicast, mapped, NAT64 and unallocated space.
        if !"2000::/3"
            .parse::<IpNet>()
            .is_ok_and(|net| net.contains(&ip))
        {
            return false;
        }
    }
    !DENIED
        .iter()
        .any(|cidr| cidr.parse::<IpNet>().map_or(true, |net| net.contains(&ip)))
}

#[allow(clippy::disallowed_methods)] // Client construction belongs in this crate.
async fn pin(url: &Url, policy: &Policy) -> Result<Client, PinError> {
    let host = hostname(url)?;
    let allowed_private = policy.allow_private_hosts.contains(&host);
    if !allowed_private
        && (host == "localhost"
            || host.ends_with(".localhost")
            || host.ends_with(".local")
            || host.ends_with(".internal"))
    {
        return Err(PinError::Address);
    }
    let ips: Vec<IpAddr> = match host.parse::<IpAddr>() {
        Ok(ip) => vec![ip],
        Err(_) => {
            let name = host.parse::<Name>().map_err(|_| PinError::Dns)?;
            tokio::time::timeout(policy.timeout, policy.resolver.resolve(name))
                .await
                .map_err(|_| PinError::Timeout)?
                .map_err(|_| PinError::Dns)?
                .map(|address| address.ip())
                .collect()
        }
    };
    if ips.is_empty()
        || ips.iter().any(|ip| {
            matches!(ip, IpAddr::V6(v6) if v6.to_ipv4_mapped().is_some())
                || (!allowed_private && !public(*ip))
        })
    {
        return Err(PinError::Address);
    }
    let addresses: Vec<_> = ips.into_iter().map(|ip| SocketAddr::new(ip, 0)).collect();
    crate::install_crypto_provider();
    let mut builder = Client::builder()
        .https_only(url.scheme() != "http")
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(policy.timeout)
        .connect_timeout(crate::CONNECT_TIMEOUT)
        .read_timeout(crate::READ_TIMEOUT)
        .dns_resolver(Arc::new(NoDns))
        .resolve_to_addrs(url.host_str().ok_or(PinError::Url)?, &addresses);
    for cert in &policy.root_certificates {
        builder = builder.add_root_certificate(cert.clone());
    }
    Ok(builder.build()?)
}

/// Default cap on a [`PinnedRequest`] response body (decoded bytes).
pub const DEFAULT_RESPONSE_LIMIT: usize = 8 * 1024 * 1024;

/// Headers that always count as credentials, even when given as public.
const CREDENTIAL_HEADERS: &[&str] = &[
    "authorization",
    "proxy-authorization",
    "cookie",
    "x-api-key",
    "api-key",
    "x-goog-api-key",
    "chatgpt-account-id",
];

impl PinnedClient {
    /// Download decoded bytes with a hard cap. No caller headers can leak on redirects.
    pub async fn fetch(&self, url: &str, limit: usize) -> Result<Vec<u8>, PinError> {
        let request = self
            .request(Method::GET, url)
            .public_header("Accept", "application/json, application/octet-stream")
            .limit(limit);
        Ok(request.exchange(true).await?.body)
    }

    /// Start a request to this client's origin. Nothing is sent until [`PinnedRequest::send`].
    pub fn request(&self, method: Method, url: &str) -> PinnedRequest<'_> {
        PinnedRequest {
            client: self,
            method,
            url: url.to_owned(),
            credentials: Vec::new(),
            public: Vec::new(),
            body: None,
            timeout: None,
            limit: DEFAULT_RESPONSE_LIMIT,
            invalid: None,
        }
    }
}

/// A request through a [`PinnedClient`]. Every hop is resolved once, address-checked
/// and pinned. Credential headers are sent only while the request stays at the
/// origin it started on; a redirect to another origin drops them for good.
/// Header values are marked sensitive and are never logged or put in errors.
/// There is deliberately no `Debug` implementation.
pub struct PinnedRequest<'a> {
    client: &'a PinnedClient,
    method: Method,
    url: String,
    credentials: Vec<(HeaderName, HeaderValue)>,
    public: Vec<(HeaderName, HeaderValue)>,
    body: Option<Vec<u8>>,
    timeout: Option<Duration>,
    limit: usize,
    invalid: Option<PinError>,
}

fn header_pair(name: &str, value: &str) -> Option<(HeaderName, HeaderValue)> {
    let name = HeaderName::from_bytes(name.as_bytes()).ok()?;
    let mut value = HeaderValue::from_str(value).ok()?;
    value.set_sensitive(true);
    Some((name, value))
}

impl PinnedRequest<'_> {
    /// A credential or other caller header (`Authorization`, `x-api-key`, ...).
    /// It is never forwarded to a different origin.
    pub fn header(mut self, name: &str, value: &str) -> Self {
        match header_pair(name, value) {
            Some(pair) => self.credentials.push(pair),
            None => self.invalid = Some(PinError::Header),
        }
        self
    }

    /// A non-secret header (`Accept`, `anthropic-version`, ...) that may follow
    /// a redirect to another origin. Known credential names are still treated
    /// as credentials.
    pub fn public_header(mut self, name: &str, value: &str) -> Self {
        match header_pair(name, value) {
            Some((name, value)) if CREDENTIAL_HEADERS.contains(&name.as_str()) => {
                self.credentials.push((name, value));
            }
            Some(pair) => self.public.push(pair),
            None => self.invalid = Some(PinError::Header),
        }
        self
    }

    /// A JSON body, sent with `Content-Type: application/json`.
    pub fn json<T: serde::Serialize + ?Sized>(mut self, body: &T) -> Self {
        match serde_json::to_vec(body) {
            Ok(bytes) => self.body = Some(bytes),
            Err(_) => self.invalid = Some(PinError::Body),
        }
        self
    }

    /// Deadline for the whole exchange: every hop, its DNS check and the body.
    /// Without it each hop is bounded by [`Policy::timeout`].
    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = Some(timeout);
        self
    }

    /// Cap on the decoded response body; [`DEFAULT_RESPONSE_LIMIT`] otherwise.
    pub fn limit(mut self, limit: usize) -> Self {
        self.limit = limit;
        self
    }

    /// Send it. Any final status is returned; use [`PinnedResponse::error_for_status`].
    pub async fn send(self) -> Result<PinnedResponse, PinError> {
        self.exchange(false).await
    }

    async fn exchange(mut self, strict: bool) -> Result<PinnedResponse, PinError> {
        if let Some(error) = self.invalid.take() {
            return Err(error);
        }
        match self.timeout {
            Some(deadline) => tokio::time::timeout(deadline, self.hops(strict))
                .await
                .map_err(|_| PinError::Timeout)?,
            None => self.hops(strict).await,
        }
    }

    async fn hops(self, strict: bool) -> Result<PinnedResponse, PinError> {
        let pinned = self.client;
        let mut current = parse_url(&self.url, &pinned.policy)?;
        if current.origin() != pinned.origin.origin() {
            return Err(PinError::Url);
        }
        let mut client = pinned.client.clone();
        let mut method = self.method;
        let mut body = self.body;
        let mut send_credentials = true;
        let mut redirects = 0;
        loop {
            let mut builder = client.request(method.clone(), current.clone());
            let credentials = self.credentials.iter().filter(|_| send_credentials);
            for (name, value) in self.public.iter().chain(credentials) {
                builder = builder.header(name, value);
            }
            if let Some(bytes) = &body {
                builder = builder
                    .header(CONTENT_TYPE, "application/json")
                    .body(bytes.clone());
            }
            let mut response = builder.send().await?;
            let status = response.status();
            if matches!(status.as_u16(), 301 | 302 | 303 | 307 | 308) {
                if redirects >= pinned.policy.max_redirects {
                    return Err(PinError::Redirect);
                }
                let location = response
                    .headers()
                    .get(reqwest::header::LOCATION)
                    .and_then(|value| value.to_str().ok())
                    .ok_or(PinError::Redirect)?;
                let next = current.join(location).map_err(|_| PinError::Redirect)?;
                let next = parse_url(next.as_str(), &pinned.policy)?;
                let same_origin = next.origin() == current.origin();
                let keeps_method = matches!(status.as_u16(), 307 | 308);
                if !keeps_method && (status == StatusCode::SEE_OTHER || method == Method::POST) {
                    // As httpx: 303, and 301/302 after POST, become a bodiless GET.
                    method = Method::GET;
                    body = None;
                }
                if body.is_some() && !same_origin {
                    // A body may carry secrets too; it never moves to another origin.
                    return Err(PinError::Redirect);
                }
                send_credentials &= same_origin;
                client = pin(&next, &pinned.policy).await?;
                current = next;
                redirects += 1;
                continue;
            }
            if strict {
                response.error_for_status_ref()?;
                if !status.is_success() {
                    return Err(PinError::Status);
                }
            }
            if response
                .content_length()
                .is_some_and(|size| size > self.limit as u64)
            {
                return Err(PinError::Size);
            }
            let headers = response.headers().clone();
            let mut bytes = Vec::new();
            while let Some(chunk) = response.chunk().await? {
                if chunk.len() > self.limit.saturating_sub(bytes.len()) {
                    return Err(PinError::Size);
                }
                bytes.extend_from_slice(&chunk);
            }
            return Ok(PinnedResponse {
                status,
                headers,
                body: bytes,
            });
        }
    }
}

/// A complete, size-capped response. No `Debug`: response headers stay out of logs.
pub struct PinnedResponse {
    pub status: StatusCode,
    pub headers: HeaderMap,
    pub body: Vec<u8>,
}

impl PinnedResponse {
    /// [`PinError::Status`] unless the status is 2xx (httpx `raise_for_status`).
    pub fn error_for_status(self) -> Result<Self, PinError> {
        if self.status.is_success() {
            Ok(self)
        } else {
            Err(PinError::Status)
        }
    }

    pub fn json<T: serde::de::DeserializeOwned>(&self) -> Result<T, PinError> {
        serde_json::from_slice(&self.body).map_err(|_| PinError::Json)
    }
}
