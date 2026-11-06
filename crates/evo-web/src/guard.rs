//! Which addresses a fetch may reach: public internet only.
//!
//! The check runs on every address a host name resolves to, at connection
//! time (a custom DNS resolver), so redirects and DNS rebinding cannot reach
//! loopback, private networks, link-local or cloud metadata addresses. IP
//! literals in URLs skip DNS, so [`check_url`] checks them on every hop.

use std::future::Future;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, ToSocketAddrs};
use std::pin::Pin;

use reqwest::dns::{Addrs, Name, Resolve, Resolving};
use url::{Host, Url};

fn public_v4(ip: Ipv4Addr) -> bool {
    let [a, b, c, _] = ip.octets();
    !(ip.is_unspecified()
        || ip.is_loopback()
        || ip.is_private()
        || ip.is_link_local()
        || ip.is_broadcast()
        || ip.is_multicast()
        || ip.is_documentation()
        || a == 0
        || a >= 240
        // Carrier-grade NAT 100.64.0.0/10.
        || (a == 100 && (64..128).contains(&b))
        // IETF protocol assignments 192.0.0.0/24.
        || (a == 192 && b == 0 && c == 0)
        // Benchmarking 198.18.0.0/15.
        || (a == 198 && (b == 18 || b == 19)))
}

fn public_v6(ip: Ipv6Addr) -> bool {
    if let Some(v4) = ip.to_ipv4_mapped() {
        return public_v4(v4);
    }
    let s = ip.segments();
    // NAT64 64:ff9b::/96 and 6to4 2002::/16 carry an IPv4 address.
    if s[0] == 0x64 && s[1] == 0xff9b && s[2..6] == [0, 0, 0, 0] {
        return public_v4(Ipv4Addr::new((s[6] >> 8) as u8, s[6] as u8, (s[7] >> 8) as u8, s[7] as u8));
    }
    if s[0] == 0x2002 {
        return public_v4(Ipv4Addr::new((s[1] >> 8) as u8, s[1] as u8, (s[2] >> 8) as u8, s[2] as u8));
    }
    !(ip.is_unspecified()
        || ip.is_loopback()
        || ip.is_multicast()
        // Unique local fc00::/7, link-local fe80::/10, site-local fec0::/10.
        || (s[0] & 0xfe00) == 0xfc00
        || (s[0] & 0xffc0) == 0xfe80
        || (s[0] & 0xffc0) == 0xfec0
        // Documentation 2001:db8::/32.
        || (s[0] == 0x2001 && s[1] == 0x0db8)
        // IPv4-compatible ::a.b.c.d (deprecated) and the rest of ::/96.
        || s[0..6] == [0, 0, 0, 0, 0, 0])
}

/// Whether `ip` is on the public internet.
pub fn is_public(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => public_v4(v4),
        IpAddr::V6(v6) => public_v6(v6),
    }
}

/// A URL a fetch may start from or be redirected to.
pub fn check_url(url: &Url) -> Result<(), String> {
    if !matches!(url.scheme(), "http" | "https") {
        return Err(format!("only http and https URLs can be fetched, not {}:", url.scheme()));
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err("URLs with a user name or password are not fetched".into());
    }
    match url.host() {
        None => Err("the URL has no host".into()),
        Some(Host::Ipv4(ip)) if !public_v4(ip) => Err(format!("{ip} is not a public address")),
        Some(Host::Ipv6(ip)) if !public_v6(ip) => Err(format!("{ip} is not a public address")),
        Some(Host::Domain(d)) if d.eq_ignore_ascii_case("localhost") || d.ends_with(".localhost") => {
            Err("localhost is not fetched".into())
        }
        _ => Ok(()),
    }
}

/// Resolves host names and keeps only public addresses.
pub struct PublicResolver;

impl Resolve for PublicResolver {
    fn resolve(&self, name: Name) -> Resolving {
        let host = name.as_str().to_string();
        let fut: Pin<Box<dyn Future<Output = _> + Send>> = Box::pin(async move {
            let lookup = host.clone();
            let addrs: Vec<SocketAddr> = tokio::task::spawn_blocking(move || {
                (lookup.as_str(), 0u16).to_socket_addrs().map(|a| a.collect::<Vec<_>>())
            })
            .await
            .map_err(|e| Box::new(e) as Box<dyn std::error::Error + Send + Sync>)?
            .map_err(|e| Box::new(e) as Box<dyn std::error::Error + Send + Sync>)?;
            let public: Vec<SocketAddr> = addrs.into_iter().filter(|a| is_public(a.ip())).collect();
            if public.is_empty() {
                return Err(format!("{host} does not resolve to a public address").into());
            }
            Ok(Box::new(public.into_iter()) as Addrs)
        });
        fut
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ip(s: &str) -> IpAddr {
        s.parse().unwrap()
    }

    #[test]
    fn private_and_special_addresses_are_refused() {
        for blocked in [
            "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1",
            "0.0.0.0", "224.0.0.1", "255.255.255.255", "198.18.0.1", "::1", "::", "fc00::1", "fd12::1",
            "fe80::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::",
            "2001:db8::1",
        ] {
            assert!(!is_public(ip(blocked)), "{blocked} should be refused");
        }
        for allowed in ["1.1.1.1", "93.184.216.34", "2606:4700:4700::1111", "::ffff:8.8.8.8"] {
            assert!(is_public(ip(allowed)), "{allowed} should be allowed");
        }
    }

    #[test]
    fn urls_are_checked() {
        let ok = |s: &str| check_url(&Url::parse(s).unwrap());
        assert!(ok("https://example.com/a").is_ok());
        assert!(ok("http://127.0.0.1/").is_err());
        assert!(ok("http://[::1]/").is_err());
        assert!(ok("http://localhost:8080/").is_err());
        assert!(ok("file:///etc/passwd").is_err());
        assert!(ok("https://user:pw@example.com/").is_err());
        assert!(ok("http://169.254.169.254/latest/meta-data").is_err());
    }
}
