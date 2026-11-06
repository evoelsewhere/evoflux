//! Marketplaces: catalogs of plugins in a git repository or a folder.
//!
//! Where a marketplace comes from ([`MarketplaceSource::parse`]):
//! * `owner/repo` (or `owner/repo#ref`) — a GitHub repository;
//! * any git URL — `https://…`, `http://…`, `git@host:…`, `ssh://…`,
//!   `file://…` — optionally `#ref` for a branch, tag or commit;
//! * a local folder, used where it is.
//!
//! The catalog is `.evo-plugin/marketplace.json`, `.claude-plugin/marketplace.json`
//! or `marketplace.json` at the repository root (first found wins): `{name, owner, description, plugins: [entry]}`. An
//! entry has `name`, `source`, and optional `description`, `version`,
//! `author`, `homepage`, `category`, `keywords`. A `source` is a path inside
//! the marketplace (`./plugins/x`, or a bare name under `metadata.pluginRoot`),
//! `{"source": "github", "repo": "owner/repo", "ref"?}`, `{"source": "url",
//! "url": <git url>, "ref"?}` or `{"source": "git-subdir", "url", "path",
//! "ref"?}`.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::manifest::read_json;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum MarketplaceSource {
    /// A git repository (GitHub `owner/repo` is stored as its URL).
    Git {
        url: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        reference: Option<String>,
    },
    /// A folder on this computer, read in place.
    Directory { path: PathBuf },
}

impl MarketplaceSource {
    /// `owner/repo[#ref]`, a git URL `[#ref]`, or an existing folder.
    pub fn parse(input: &str) -> Result<Self, String> {
        let input = input.trim();
        if input.is_empty() {
            return Err("enter owner/repo, a git URL or a folder".into());
        }
        let local = Path::new(input);
        if local.is_dir() {
            return Ok(MarketplaceSource::Directory {
                path: local.to_path_buf(),
            });
        }
        let (base, reference) = match input.rsplit_once('#') {
            Some((base, r)) if !r.is_empty() && !base.is_empty() => (base, Some(r.to_string())),
            _ => (input, None),
        };
        let is_url = ["https://", "http://", "ssh://", "git://", "file://"]
            .iter()
            .any(|p| base.starts_with(p))
            || (base.starts_with("git@") && base.contains(':'));
        if is_url {
            return Ok(MarketplaceSource::Git {
                url: base.to_string(),
                reference,
            });
        }
        let parts: Vec<&str> = base.split('/').collect();
        let github_part = |s: &str| {
            !s.is_empty()
                && s.chars()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
        };
        if parts.len() == 2 && parts.iter().all(|p| github_part(p)) {
            let repo = parts[1].trim_end_matches(".git");
            return Ok(MarketplaceSource::Git {
                url: format!("https://github.com/{}/{repo}.git", parts[0]),
                reference,
            });
        }
        Err(format!(
            "`{input}` is not owner/repo, a git URL or a folder that exists"
        ))
    }

    /// How it reads for people.
    pub fn display(&self) -> String {
        match self {
            MarketplaceSource::Git { url, reference } => {
                let short = url
                    .strip_prefix("https://github.com/")
                    .map(|r| r.trim_end_matches(".git").to_string())
                    .unwrap_or_else(|| url.clone());
                match reference {
                    Some(r) => format!("{short}#{r}"),
                    None => short,
                }
            }
            MarketplaceSource::Directory { path } => path.display().to_string(),
        }
    }
}

/// The catalog file in a marketplace folder.
pub fn catalog_path(root: &Path) -> Option<PathBuf> {
    [
        root.join(".evo-plugin").join("marketplace.json"),
        root.join(".claude-plugin").join("marketplace.json"),
        root.join("marketplace.json"),
    ]
    .into_iter()
    .find(|p| p.is_file())
}

/// A marketplace as added: where it came from and where its files are.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Marketplace {
    pub name: String,
    pub source: MarketplaceSource,
    /// The clone, or the folder itself.
    pub location: PathBuf,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub owner: Option<String>,
    /// Milliseconds since the Unix epoch.
    #[serde(default)]
    pub updated_at: u64,
}

impl Marketplace {
    /// The catalog's raw JSON.
    pub fn catalog(&self) -> Result<Value, String> {
        let path = catalog_path(&self.location)
            .ok_or_else(|| format!("{} has no marketplace.json", self.location.display()))?;
        read_json(&path)
    }

    /// The plugin entries (each with `name`, `source`, …).
    pub fn entries(&self) -> Result<Vec<Value>, String> {
        Ok(self
            .catalog()?
            .get("plugins")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default())
    }

    pub fn entry(&self, plugin: &str) -> Result<Value, String> {
        self.entries()?
            .into_iter()
            .find(|e| e.get("name").and_then(Value::as_str) == Some(plugin))
            .ok_or_else(|| format!("{} has no plugin `{plugin}`", self.name))
    }
}

/// Where a plugin's files come from.
#[derive(Debug, Clone, PartialEq)]
pub enum PluginSource {
    /// A folder inside the marketplace.
    Local(PathBuf),
    /// A git repository, optionally a folder inside it.
    Git {
        url: String,
        reference: Option<String>,
        subdir: Option<String>,
    },
}

/// Resolve an entry's `source` against the marketplace.
pub fn plugin_source(marketplace: &Marketplace, entry: &Value) -> Result<PluginSource, String> {
    let root_hint = marketplace.catalog().ok().and_then(|c| {
        c.pointer("/metadata/pluginRoot")
            .and_then(Value::as_str)
            .map(str::to_string)
    });
    let inside = |relative: &str| -> Result<PathBuf, String> {
        let clean = relative.trim().trim_start_matches("./");
        if clean.split(['/', '\\']).any(|p| p == "..") {
            return Err(format!("`{relative}` leaves the marketplace"));
        }
        let base = match (&root_hint, relative.starts_with("./")) {
            (Some(hint), false) => marketplace.location.join(hint.trim_start_matches("./")),
            _ => marketplace.location.clone(),
        };
        Ok(base.join(clean))
    };
    match entry.get("source") {
        Some(Value::String(path)) => Ok(PluginSource::Local(inside(path)?)),
        Some(Value::Object(source)) => {
            let get = |k: &str| source.get(k).and_then(Value::as_str).map(str::to_string);
            let reference = get("sha").or_else(|| get("ref"));
            match get("source").as_deref() {
                Some("github") => {
                    let repo = get("repo").ok_or("a github source needs `repo`")?;
                    Ok(PluginSource::Git {
                        url: format!("https://github.com/{}.git", repo.trim_end_matches(".git")),
                        reference,
                        subdir: None,
                    })
                }
                Some("url") | Some("git") => Ok(PluginSource::Git {
                    url: get("url").ok_or("a url source needs `url`")?,
                    reference,
                    subdir: None,
                }),
                Some("git-subdir") => Ok(PluginSource::Git {
                    url: get("url").ok_or("a git-subdir source needs `url`")?,
                    reference,
                    subdir: Some(get("path").ok_or("a git-subdir source needs `path`")?),
                }),
                Some(other) => Err(format!("`{other}` plugin sources are not supported yet")),
                None => Err("the plugin's source has no `source` kind".into()),
            }
        }
        _ => Err("the plugin entry has no source".into()),
    }
}

/// Clone `url` (at `reference`) into `dest`, shallow when possible.
pub fn clone(url: &str, reference: Option<&str>, dest: &Path) -> Result<(), String> {
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let dest_str = dest.to_string_lossy().to_string();
    let looks_like_sha =
        reference.is_some_and(|r| r.len() >= 7 && r.chars().all(|c| c.is_ascii_hexdigit()));
    match reference {
        Some(r) if !looks_like_sha => crate::git(
            &["clone", "--depth", "1", "--branch", r, url, &dest_str],
            None,
        )
        .map(|_| ()),
        Some(sha) => {
            crate::git(&["clone", url, &dest_str], None)?;
            crate::git(&["checkout", "--quiet", sha], Some(dest)).map(|_| ())
        }
        None => crate::git(&["clone", "--depth", "1", url, &dest_str], None).map(|_| ()),
    }
}

/// The short commit of a clone.
pub fn head(dir: &Path) -> Option<String> {
    crate::git(&["rev-parse", "--short=12", "HEAD"], Some(dir)).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sources_parse() {
        assert_eq!(
            MarketplaceSource::parse("acme/tools").unwrap(),
            MarketplaceSource::Git {
                url: "https://github.com/acme/tools.git".into(),
                reference: None
            }
        );
        assert_eq!(
            MarketplaceSource::parse("acme/tools#v2").unwrap(),
            MarketplaceSource::Git {
                url: "https://github.com/acme/tools.git".into(),
                reference: Some("v2".into())
            }
        );
        assert_eq!(
            MarketplaceSource::parse("https://gitlab.example.com/team/plugins.git#main").unwrap(),
            MarketplaceSource::Git {
                url: "https://gitlab.example.com/team/plugins.git".into(),
                reference: Some("main".into())
            }
        );
        assert!(matches!(
            MarketplaceSource::parse("git@github.com:acme/tools.git").unwrap(),
            MarketplaceSource::Git { .. }
        ));
        let dir = tempfile::tempdir().unwrap();
        assert!(matches!(
            MarketplaceSource::parse(&dir.path().to_string_lossy()).unwrap(),
            MarketplaceSource::Directory { .. }
        ));
        assert!(MarketplaceSource::parse("not a source").is_err());
        assert_eq!(
            MarketplaceSource::parse("acme/tools#v2").unwrap().display(),
            "acme/tools#v2"
        );
    }

    #[test]
    fn catalog_in_either_plugin_folder() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        assert_eq!(catalog_path(root), None);
        let claude = root.join(".claude-plugin");
        std::fs::create_dir_all(&claude).unwrap();
        std::fs::write(claude.join("marketplace.json"), "{}").unwrap();
        assert_eq!(catalog_path(root), Some(claude.join("marketplace.json")));
        let evo = root.join(".evo-plugin");
        std::fs::create_dir_all(&evo).unwrap();
        std::fs::write(evo.join("marketplace.json"), "{}").unwrap();
        assert_eq!(catalog_path(root), Some(evo.join("marketplace.json")));
    }
}
