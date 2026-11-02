//! The `urllib.parse.urlsplit` checks of `ConductorSettings._validate_connection`.

/// `url.strip().rstrip("/")`.
pub(crate) fn strip_origin(url: &str) -> String {
    url.trim().trim_end_matches('/').to_owned()
}

/// `urlsplit(value)` has an `http`/`https` scheme, a hostname, no user info,
/// no query or fragment, and an empty or `/` path.
pub(crate) fn is_plain_http_origin(value: &str) -> bool {
    // urlsplit drops leading C0 controls and spaces, and tabs and newlines anywhere.
    let url: String = value
        .trim_start_matches(|c: char| c <= ' ')
        .chars()
        .filter(|c| !matches!(c, '\t' | '\r' | '\n'))
        .collect();
    let mut rest = url.as_str();
    let mut scheme = String::new();
    if let Some(colon) = rest.find(':') {
        let candidate = rest.get(..colon).unwrap_or_default();
        if candidate
            .chars()
            .next()
            .is_some_and(|c| c.is_ascii_alphabetic())
            && candidate
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '-' | '.'))
        {
            scheme = candidate.to_ascii_lowercase();
            rest = rest.get(colon + 1..).unwrap_or_default();
        }
    }
    let mut netloc = "";
    if let Some(after) = rest.strip_prefix("//") {
        let end = after.find(['/', '?', '#']).unwrap_or(after.len());
        netloc = after.get(..end).unwrap_or_default();
        rest = after.get(end..).unwrap_or_default();
        if netloc.contains('[') != netloc.contains(']') {
            // urlsplit raises "Invalid IPv6 URL"; the validator fails either way.
            return false;
        }
    }
    let (rest, fragment) = rest.split_once('#').unwrap_or((rest, ""));
    let (path, query) = rest.split_once('?').unwrap_or((rest, ""));
    let host_port = netloc.rsplit_once('@').map_or(netloc, |(_, h)| h);
    let hostname = match host_port.strip_prefix('[') {
        Some(bracketed) => bracketed.split_once(']').map_or("", |(h, _)| h),
        None => host_port.split_once(':').map_or(host_port, |(h, _)| h),
    };
    matches!(scheme.as_str(), "http" | "https")
        && !hostname.is_empty()
        && !netloc.contains('@')
        && query.is_empty()
        && fragment.is_empty()
        && (path.is_empty() || path == "/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn origins_follow_urlsplit() {
        for ok in [
            "https://x.example",
            "HTTPS://X.example",
            "http://Example.com:8443",
            "https://[::1]:8443",
            "https://x.example?",
            "https://x.example#",
            "https://x.example/",
        ] {
            assert!(is_plain_http_origin(ok), "{ok}");
        }
        for bad in [
            "ftp://x",
            "http://",
            "https://user:pw@example.com",
            "https://@example.com",
            "https://example.com/path",
            "https://example.com?q=1",
            "https://x.example#frag",
            "https://[::1",
            "example.com",
            "1http://x",
        ] {
            assert!(!is_plain_http_origin(bad), "{bad}");
        }
        assert_eq!(
            strip_origin("  http://Example.com:8443//  "),
            "http://Example.com:8443"
        );
    }
}
