//! Port of app/plugin_platform/marketplaces.py::_fetch_bytes; pins DNS to close rebinding.

use ipnet::IpNet;
use reqwest::dns::{Addrs, Name, Resolve, Resolving};
use reqwest::{Client, Url};
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
}

/// Private opt-in names are normalized hostnames, without brackets or a port.
/// Opt-in never transfers to a different redirect host. Mapped IPv6 is forbidden.
#[derive(Clone)]
pub struct Policy {
    pub allow_private_hosts: HashSet<String>,
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
        parse_url(host)?
    } else {
        parse_url(&format!("https://{host}/"))?
    };
    let client = pin(&origin, &policy).await?;
    Ok(PinnedClient {
        origin,
        client,
        policy,
    })
}

fn parse_url(value: &str) -> Result<Url, PinError> {
    if value.len() > 2048 || value.contains('\\') {
        return Err(PinError::Url);
    }
    let url = Url::parse(value).map_err(|_| PinError::Url)?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err(PinError::Url);
    }
    Ok(url)
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
        .https_only(true)
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

impl PinnedClient {
    /// Download decoded bytes with a hard cap. No caller headers can leak on redirects.
    pub async fn fetch(&self, url: &str, limit: usize) -> Result<Vec<u8>, PinError> {
        let mut current = parse_url(url)?;
        if current.origin() != self.origin.origin() {
            return Err(PinError::Url);
        }
        let mut client = self.client.clone();
        let mut redirects = 0;
        loop {
            let mut response = client
                .get(current.clone())
                .header("Accept", "application/json, application/octet-stream")
                .send()
                .await?;
            if matches!(response.status().as_u16(), 301 | 302 | 303 | 307 | 308) {
                if redirects >= self.policy.max_redirects {
                    return Err(PinError::Redirect);
                }
                let location = response
                    .headers()
                    .get(reqwest::header::LOCATION)
                    .and_then(|value| value.to_str().ok())
                    .ok_or(PinError::Redirect)?;
                let next = current.join(location).map_err(|_| PinError::Redirect)?;
                current = parse_url(next.as_str())?;
                client = pin(&current, &self.policy).await?;
                redirects += 1;
                continue;
            }
            response.error_for_status_ref()?;
            if !response.status().is_success() {
                return Err(PinError::Status);
            }
            if response
                .content_length()
                .is_some_and(|size| size > limit as u64)
            {
                return Err(PinError::Size);
            }
            let mut bytes = Vec::new();
            while let Some(chunk) = response.chunk().await? {
                if chunk.len() > limit.saturating_sub(bytes.len()) {
                    return Err(PinError::Size);
                }
                bytes.extend_from_slice(&chunk);
            }
            return Ok(bytes);
        }
    }
}
