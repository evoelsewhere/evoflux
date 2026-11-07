//! The pinned description of the downloadable LibreOffice runtime.
//!
//! The runtime is a trimmed LibreOffice build published as release assets (see
//! `scripts/office-runtime/`). Only an archive whose SHA-256 and size match the
//! asset pinned in this file is ever installed, so a compromised mirror or
//! release page cannot substitute another binary: the pin ships inside the
//! application itself.
//!
//! `EVO_OFFICE_MANIFEST` may point at a JSON file of the same shape
//! (`{"<platform>": {...}}`) to test a locally built bundle. It still has to pass
//! every check below; it is also the only way a `file://` URL is accepted.

use std::path::Path;

use serde::Deserialize;

/// Directory name of the runtime under the runtimes folder.
pub const RUNTIME_ID: &str = "libreoffice";
/// Every archive member and the executable live under this top-level folder.
pub const RUNTIME_ROOT: &str = "soffice";
/// Environment variable that replaces the pinned manifest (tests only).
pub const MANIFEST_OVERRIDE_ENV: &str = "EVO_OFFICE_MANIFEST";

const MAX_ARCHIVE_BYTES: u64 = 1024 * 1024 * 1024;

/// One verified, installable runtime archive for a single platform.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Asset {
    pub platform: String,
    pub version: String,
    pub url: String,
    pub sha256: String,
    pub size: u64,
    /// Path of `soffice` inside the archive, always under [`RUNTIME_ROOT`].
    pub executable: String,
    /// Disk space the extracted runtime takes. Display only.
    pub installed_size: Option<u64>,
}

/// A manifest record as written in JSON.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Record {
    version: String,
    url: String,
    sha256: String,
    size: u64,
    executable: String,
    #[serde(default)]
    installed_size: Option<u64>,
}

const RELEASE: &str =
    "https://github.com/evoelsewhere/evo-harness/releases/download/office-runtime-26.8.0";

/// platform key, sha256, size, executable, installed size.
const PINNED: &[(&str, &str, u64, &str, u64)] = &[
    (
        "darwin-arm64",
        "a359b352d98e8b27ad3e1a1fd638ac4ea346c744a333618526b9f6e95c343781",
        196_792_574,
        "soffice/LibreOffice.app/Contents/MacOS/soffice",
        630_987_908,
    ),
    (
        "darwin-x64",
        "fd94cf6efa5462d1eff3447065b4ff214784893fb5661058305f03f56acf32c5",
        205_432_455,
        "soffice/LibreOffice.app/Contents/MacOS/soffice",
        641_489_649,
    ),
    (
        "linux-x64",
        "9ba0a492cbeb7515a1df9ffe47e454431766f4f45e36075bd0b5f75c34350f10",
        175_909_950,
        "soffice/program/soffice",
        496_738_531,
    ),
    (
        "win32-x64",
        "1a62986fc981250f55eb0f3b41c9b6eaf9db52a2538f14d27b7b1b7a3c8c47f1",
        191_184_974,
        "soffice/program/soffice.exe",
        635_851_559,
    ),
];

const PINNED_VERSION: &str = "26.8.0";

/// The runtime platform key of this machine (`win32-x64`, `darwin-arm64`, …).
pub fn platform_key() -> Option<String> {
    let arch = match std::env::consts::ARCH {
        "x86_64" => "x64",
        "aarch64" => "arm64",
        _ => return None,
    };
    let system = match std::env::consts::OS {
        "windows" => "win32",
        "macos" => "darwin",
        "linux" => "linux",
        _ => return None,
    };
    Some(format!("{system}-{arch}"))
}

pub(crate) fn safe_executable(value: &str) -> Result<String, String> {
    let normalized = value.replace('\\', "/");
    let mut parts = normalized.split('/');
    let first = parts.next().unwrap_or("");
    let rest: Vec<&str> = parts.collect();
    if first != RUNTIME_ROOT
        || rest.is_empty()
        || normalized.starts_with('/')
        || normalized
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
        || normalized.contains(':')
    {
        return Err(format!(
            "Runtime executable must live under {RUNTIME_ROOT}/"
        ));
    }
    Ok(normalized)
}

/// Validate a record for `platform`.
fn parse_record(platform: &str, record: Record, allow_file_urls: bool) -> Result<Asset, String> {
    let version = record.version;
    if version.is_empty()
        || version.len() > 64
        || !version
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "._+-".contains(c))
    {
        return Err("Runtime version is not a safe identifier".into());
    }
    let sha256 = record.sha256.to_ascii_lowercase();
    if sha256.len() != 64 || !sha256.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("Runtime sha256 must be 64 hex characters".into());
    }
    if record.size == 0 || record.size > MAX_ARCHIVE_BYTES {
        return Err("Runtime archive size is out of range".into());
    }
    let url = url::Url::parse(&record.url).map_err(|e| format!("Runtime URL is invalid: {e}"))?;
    if !(url.scheme() == "https" || (allow_file_urls && url.scheme() == "file")) {
        return Err("Runtime archives are only fetched over HTTPS".into());
    }
    Ok(Asset {
        platform: platform.to_string(),
        version,
        url: record.url,
        sha256,
        size: record.size,
        executable: safe_executable(&record.executable)?,
        installed_size: record
            .installed_size
            .filter(|n| *n > 0 && *n <= 16 * MAX_ARCHIVE_BYTES),
    })
}

/// Parse an override manifest (`{"<platform>": {...}}`) and return `platform`'s asset.
pub fn asset_from_json(platform: &str, json: &str) -> Result<Option<Asset>, String> {
    let mut all: std::collections::HashMap<String, Record> =
        serde_json::from_str(json).map_err(|e| format!("Manifest is not valid: {e}"))?;
    all.remove(platform)
        .map(|record| parse_record(platform, record, true))
        .transpose()
}

fn pinned(platform: &str) -> Option<Asset> {
    let (key, sha256, size, executable, installed) = PINNED.iter().find(|p| p.0 == platform)?;
    parse_record(
        key,
        Record {
            version: PINNED_VERSION.into(),
            url: format!("{RELEASE}/libreoffice-{PINNED_VERSION}-{key}.tar.gz"),
            sha256: (*sha256).into(),
            size: *size,
            executable: (*executable).into(),
            installed_size: Some(*installed),
        },
        false,
    )
    .ok()
}

/// The verified asset for this machine, or `None` when none is published.
pub fn current_asset() -> Option<Asset> {
    let platform = platform_key()?;
    if let Ok(path) = std::env::var(MANIFEST_OVERRIDE_ENV) {
        let path = path.trim();
        if !path.is_empty() {
            let text = std::fs::read_to_string(Path::new(path)).ok()?;
            return match asset_from_json(&platform, &text) {
                Ok(asset) => asset,
                Err(error) => {
                    tracing::warn!(%error, "office runtime manifest override rejected");
                    None
                }
            };
        }
    }
    pinned(&platform)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(url: &str, sha: &str, exe: &str) -> Record {
        Record {
            version: "1.0".into(),
            url: url.into(),
            sha256: sha.into(),
            size: 10,
            executable: exe.into(),
            installed_size: None,
        }
    }

    const SHA: &str = "a359b352d98e8b27ad3e1a1fd638ac4ea346c744a333618526b9f6e95c343781";

    #[test]
    fn every_pin_is_valid() {
        for (key, ..) in PINNED {
            let asset = pinned(key).unwrap_or_else(|| panic!("{key} pin is invalid"));
            assert!(asset.url.starts_with("https://"));
            assert!(asset.executable.starts_with("soffice/"));
        }
    }

    #[test]
    fn only_https_unless_overridden() {
        assert!(parse_record("p", record("http://x/a.tar.gz", SHA, "soffice/x"), false).is_err());
        assert!(
            parse_record("p", record("file:///tmp/a.tar.gz", SHA, "soffice/x"), false).is_err()
        );
        assert!(parse_record("p", record("file:///tmp/a.tar.gz", SHA, "soffice/x"), true).is_ok());
    }

    #[test]
    fn rejects_bad_checksums_and_executables() {
        let ok = "https://x/a.tar.gz";
        assert!(parse_record("p", record(ok, "abc", "soffice/x"), false).is_err());
        for exe in [
            "x/soffice",
            "soffice",
            "soffice/../x",
            "/soffice/x",
            "soffice//x",
            "soffice/C:/x",
        ] {
            assert!(
                parse_record("p", record(ok, SHA, exe), false).is_err(),
                "{exe}"
            );
        }
        assert!(parse_record("p", record(ok, SHA, "soffice\\program\\soffice.exe"), false).is_ok());
    }

    #[test]
    fn size_must_be_in_range() {
        let mut r = record("https://x/a", SHA, "soffice/x");
        r.size = 0;
        assert!(parse_record("p", r, false).is_err());
        let mut r = record("https://x/a", SHA, "soffice/x");
        r.size = MAX_ARCHIVE_BYTES + 1;
        assert!(parse_record("p", r, false).is_err());
    }

    #[test]
    fn override_json_selects_the_platform() {
        let json = format!(
            r#"{{"win32-x64":{{"version":"9","url":"file:///a.tar.gz","sha256":"{SHA}","size":5,"executable":"soffice/program/soffice.exe"}}}}"#
        );
        assert!(asset_from_json("win32-x64", &json).unwrap().is_some());
        assert!(asset_from_json("linux-x64", &json).unwrap().is_none());
        assert!(asset_from_json("win32-x64", "{").is_err());
    }
}
