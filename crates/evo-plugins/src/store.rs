//! What is installed, in `<agent dir>/plugins`:
//!
//! ```text
//! marketplaces.json          the marketplaces added (source, where, when)
//! marketplaces/<name>/       their clones (folders are read in place)
//! cache/<marketplace>/<plugin>/<version>/   installed copies
//! data/<plugin id>/          each plugin's data, kept across updates
//! installed.json             {id: {name, marketplace, version, path, enabled, config}}
//! ```

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};

use crate::manifest::{self, Plugin};
use crate::marketplace::{self, Marketplace, MarketplaceSource, PluginSource};
use crate::{copy_dir, valid_name};

/// The marketplace name for plugins added from a folder.
pub const LOCAL: &str = "local";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Installed {
    /// `name@marketplace`.
    pub id: String,
    pub name: String,
    pub marketplace: String,
    pub version: String,
    /// The installed copy (or, for a folder, the folder itself).
    pub path: PathBuf,
    pub enabled: bool,
    #[serde(default)]
    pub installed_at: u64,
    /// Values for the plugin's `userConfig`.
    #[serde(default)]
    pub config: Map<String, Value>,
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn read<T: serde::de::DeserializeOwned + Default>(path: &Path) -> T {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

fn write<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, text + "\n").map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| e.to_string())
}

fn remove_dir(path: &Path) {
    if path.exists() {
        // Git marks pack files read-only; clear that so Windows can delete them.
        fn writable(dir: &Path) {
            if let Ok(entries) = std::fs::read_dir(dir) {
                for entry in entries.flatten() {
                    let p = entry.path();
                    if p.is_dir() {
                        writable(&p);
                    } else if let Ok(meta) = std::fs::metadata(&p) {
                        let mut perms = meta.permissions();
                        #[allow(clippy::permissions_set_readonly_false)]
                        perms.set_readonly(false);
                        let _ = std::fs::set_permissions(&p, perms);
                    }
                }
            }
        }
        writable(path);
        let _ = std::fs::remove_dir_all(path);
    }
}

#[derive(Debug, Clone)]
pub struct Store {
    root: PathBuf,
}

impl Store {
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }

    /// `<agent dir>/plugins`.
    pub fn in_agent_dir(agent_dir: &Path) -> Self {
        Self::new(agent_dir.join("plugins"))
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    fn marketplaces_file(&self) -> PathBuf {
        self.root.join("marketplaces.json")
    }

    fn installed_file(&self) -> PathBuf {
        self.root.join("installed.json")
    }

    pub fn data_dir(&self, id: &str) -> PathBuf {
        let safe: String = id
            .chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                    c
                } else {
                    '-'
                }
            })
            .collect();
        self.root.join("data").join(safe)
    }

    // ── Marketplaces ────────────────────────────────────────────────────────

    pub fn marketplaces(&self) -> Vec<Marketplace> {
        let map: BTreeMap<String, Marketplace> = read(&self.marketplaces_file());
        map.into_values().collect()
    }

    pub fn marketplace(&self, name: &str) -> Result<Marketplace, String> {
        self.marketplaces()
            .into_iter()
            .find(|m| m.name == name)
            .ok_or_else(|| format!("no marketplace `{name}`"))
    }

    fn save_marketplace(&self, marketplace: Marketplace) -> Result<(), String> {
        let mut map: BTreeMap<String, Marketplace> = read(&self.marketplaces_file());
        map.insert(marketplace.name.clone(), marketplace);
        write(&self.marketplaces_file(), &map)
    }

    /// Add a marketplace from `owner/repo[#ref]`, a git URL `[#ref]`, or a folder.
    pub fn add_marketplace(&self, input: &str) -> Result<Marketplace, String> {
        let source = MarketplaceSource::parse(input)?;
        let (location, temporary) = match &source {
            MarketplaceSource::Directory { path } => (path.clone(), false),
            MarketplaceSource::Git { url, reference } => {
                let tmp = self
                    .root
                    .join("marketplaces")
                    .join(format!(".adding-{}", now_ms()));
                marketplace::clone(url, reference.as_deref(), &tmp)?;
                (tmp, true)
            }
        };
        let fail = |error: String| {
            if temporary {
                remove_dir(&location);
            }
            Err(error)
        };
        let catalog = match marketplace::catalog_path(&location).map(|p| manifest::read_json(&p)) {
            Some(Ok(catalog)) => catalog,
            Some(Err(e)) => return fail(e),
            None => {
                return fail(
                    "no .evo-plugin/marketplace.json, .claude-plugin/marketplace.json or marketplace.json there"
                        .into(),
                )
            }
        };
        let name = catalog
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if !valid_name(&name) || name == LOCAL {
            return fail(format!("the marketplace's name `{name}` cannot be used"));
        }
        if self.marketplaces().iter().any(|m| m.name == name) {
            return fail(format!("a marketplace named `{name}` is already added"));
        }
        let location = if temporary {
            let dest = self.root.join("marketplaces").join(&name);
            remove_dir(&dest);
            std::fs::rename(&location, &dest).map_err(|e| e.to_string())?;
            dest
        } else {
            location
        };
        let marketplace = Marketplace {
            name,
            source,
            location,
            description: catalog
                .get("description")
                .and_then(Value::as_str)
                .map(str::to_string),
            owner: catalog
                .pointer("/owner/name")
                .and_then(Value::as_str)
                .map(str::to_string),
            updated_at: now_ms(),
        };
        self.save_marketplace(marketplace.clone())?;
        Ok(marketplace)
    }

    /// Fetch the marketplace again (a folder is re-read as it is).
    pub fn update_marketplace(&self, name: &str) -> Result<Marketplace, String> {
        let mut marketplace = self.marketplace(name)?;
        if let MarketplaceSource::Git { url, reference } = &marketplace.source {
            let tmp = self
                .root
                .join("marketplaces")
                .join(format!(".updating-{}", now_ms()));
            marketplace::clone(url, reference.as_deref(), &tmp)?;
            remove_dir(&marketplace.location);
            std::fs::rename(&tmp, &marketplace.location).map_err(|e| e.to_string())?;
        }
        if let Ok(catalog) = marketplace.catalog() {
            marketplace.description = catalog
                .get("description")
                .and_then(Value::as_str)
                .map(str::to_string);
            marketplace.owner = catalog
                .pointer("/owner/name")
                .and_then(Value::as_str)
                .map(str::to_string);
        }
        marketplace.updated_at = now_ms();
        self.save_marketplace(marketplace.clone())?;
        Ok(marketplace)
    }

    /// Forget a marketplace (its installed plugins stay).
    pub fn remove_marketplace(&self, name: &str) -> Result<(), String> {
        let mut map: BTreeMap<String, Marketplace> = read(&self.marketplaces_file());
        let marketplace = map
            .remove(name)
            .ok_or_else(|| format!("no marketplace `{name}`"))?;
        if matches!(marketplace.source, MarketplaceSource::Git { .. }) {
            remove_dir(&marketplace.location);
        }
        write(&self.marketplaces_file(), &map)
    }

    /// Every plugin every marketplace offers, with whether it is installed.
    pub fn catalog(&self) -> Vec<Value> {
        let installed = self.installed();
        let mut out = Vec::new();
        for marketplace in self.marketplaces() {
            match marketplace.entries() {
                Ok(entries) => {
                    for mut entry in entries {
                        let name = entry
                            .get("name")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_string();
                        let id = format!("{name}@{}", marketplace.name);
                        let mine = installed.iter().find(|i| i.id == id);
                        if let Some(object) = entry.as_object_mut() {
                            object.insert("marketplace".into(), json!(marketplace.name));
                            object.insert("id".into(), json!(id));
                            object.insert("installed".into(), json!(mine.map(|i| &i.version)));
                        }
                        out.push(entry);
                    }
                }
                Err(error) => out.push(json!({ "marketplace": marketplace.name, "error": error })),
            }
        }
        out
    }

    // ── Plugins ─────────────────────────────────────────────────────────────

    pub fn installed(&self) -> Vec<Installed> {
        let map: BTreeMap<String, Installed> = read(&self.installed_file());
        map.into_values().collect()
    }

    fn save_installed(
        &self,
        change: impl FnOnce(&mut BTreeMap<String, Installed>) -> Result<(), String>,
    ) -> Result<(), String> {
        let mut map: BTreeMap<String, Installed> = read(&self.installed_file());
        change(&mut map)?;
        write(&self.installed_file(), &map)
    }

    /// Install (or reinstall) `plugin` from `marketplace`; keeps its on/off
    /// state and settings when it was installed before.
    pub fn install(&self, marketplace_name: &str, plugin: &str) -> Result<Installed, String> {
        let marketplace = self.marketplace(marketplace_name)?;
        let entry = marketplace.entry(plugin)?;
        if !valid_name(plugin) {
            return Err(format!("the plugin name `{plugin}` cannot be used"));
        }
        let source = marketplace::plugin_source(&marketplace, &entry)?;
        let staging = self
            .root
            .join("cache")
            .join(format!(".installing-{}", now_ms()));
        let (from, commit) = match &source {
            PluginSource::Local(path) => {
                if !path.is_dir() {
                    return Err(format!("{} does not exist", path.display()));
                }
                (path.clone(), None)
            }
            PluginSource::Git {
                url,
                reference,
                subdir,
            } => {
                marketplace::clone(url, reference.as_deref(), &staging)?;
                let commit = marketplace::head(&staging);
                let from = match subdir {
                    Some(sub) => staging.join(sub.trim_start_matches("./")),
                    None => staging.clone(),
                };
                if !from.is_dir() {
                    remove_dir(&staging);
                    return Err(format!(
                        "{} has no folder `{}`",
                        url,
                        subdir.as_deref().unwrap_or("")
                    ));
                }
                (from, commit)
            }
        };
        let manifest = manifest::read_manifest(&from).unwrap_or_default();
        let version = manifest
            .get("version")
            .and_then(Value::as_str)
            .or_else(|| entry.get("version").and_then(Value::as_str))
            .map(str::to_string)
            .or(commit)
            .unwrap_or_else(|| "0".into());
        let safe_version: String = version
            .chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_') {
                    c
                } else {
                    '-'
                }
            })
            .collect();
        let dest = self
            .root
            .join("cache")
            .join(&marketplace.name)
            .join(plugin)
            .join(&safe_version);
        remove_dir(&dest);
        let copied = copy_dir(&from, &dest);
        remove_dir(&staging);
        copied?;
        let id = format!("{plugin}@{}", marketplace.name);
        let mut result = None;
        self.save_installed(|map| {
            let previous = map.get(&id);
            let installed = Installed {
                id: id.clone(),
                name: plugin.to_string(),
                marketplace: marketplace.name.clone(),
                version: version.clone(),
                path: dest.clone(),
                enabled: previous.map(|p| p.enabled).unwrap_or(true),
                installed_at: now_ms(),
                config: previous.map(|p| p.config.clone()).unwrap_or_default(),
            };
            // An older version's copy is no longer needed.
            if let Some(previous) = previous {
                if previous.path != dest && previous.marketplace != LOCAL {
                    remove_dir(&previous.path);
                }
            }
            map.insert(id.clone(), installed.clone());
            result = Some(installed);
            Ok(())
        })?;
        std::fs::create_dir_all(self.data_dir(&id)).ok();
        Ok(result.unwrap())
    }

    /// Use a plugin folder on this computer where it is (`name@local`).
    pub fn install_folder(&self, folder: &Path) -> Result<Installed, String> {
        if !folder.is_dir() {
            return Err(format!("{} is not a folder", folder.display()));
        }
        let manifest = manifest::read_manifest(folder)?;
        let name = manifest
            .get("name")
            .and_then(Value::as_str)
            .map(str::to_string)
            .or_else(|| folder.file_name().map(|n| n.to_string_lossy().into_owned()))
            .unwrap_or_default();
        if !valid_name(&name) {
            return Err(format!("the plugin name `{name}` cannot be used"));
        }
        let id = format!("{name}@{LOCAL}");
        let installed = Installed {
            id: id.clone(),
            name,
            marketplace: LOCAL.into(),
            version: manifest
                .get("version")
                .and_then(Value::as_str)
                .unwrap_or("local")
                .to_string(),
            path: folder.to_path_buf(),
            enabled: true,
            installed_at: now_ms(),
            config: Map::new(),
        };
        let saved = installed.clone();
        self.save_installed(|map| {
            let config = map.get(&id).map(|p| p.config.clone()).unwrap_or_default();
            map.insert(id.clone(), Installed { config, ..saved });
            Ok(())
        })?;
        std::fs::create_dir_all(self.data_dir(&id)).ok();
        Ok(installed)
    }

    /// Install again from its marketplace, fetched fresh.
    pub fn update(&self, id: &str) -> Result<Installed, String> {
        let current = self
            .installed()
            .into_iter()
            .find(|i| i.id == id)
            .ok_or_else(|| format!("`{id}` is not installed"))?;
        if current.marketplace == LOCAL {
            return Ok(current);
        }
        self.update_marketplace(&current.marketplace)?;
        self.install(&current.marketplace, &current.name)
    }

    /// Remove a plugin (its data folder is kept).
    pub fn uninstall(&self, id: &str) -> Result<(), String> {
        self.save_installed(|map| {
            let gone = map
                .remove(id)
                .ok_or_else(|| format!("`{id}` is not installed"))?;
            if gone.marketplace != LOCAL {
                if let Some(plugin_dir) = gone.path.parent() {
                    remove_dir(plugin_dir);
                }
            }
            Ok(())
        })
    }

    pub fn set_enabled(&self, id: &str, enabled: bool) -> Result<(), String> {
        self.save_installed(|map| {
            map.get_mut(id)
                .ok_or_else(|| format!("`{id}` is not installed"))?
                .enabled = enabled;
            Ok(())
        })
    }

    pub fn set_config(&self, id: &str, config: Map<String, Value>) -> Result<(), String> {
        self.save_installed(|map| {
            map.get_mut(id)
                .ok_or_else(|| format!("`{id}` is not installed"))?
                .config = config;
            Ok(())
        })
    }

    /// One installed plugin, loaded.
    pub fn load(&self, installed: &Installed) -> Plugin {
        manifest::load(
            &installed.path,
            &installed.id,
            &installed.name,
            &self.data_dir(&installed.id),
            &installed.config,
        )
    }

    /// The plugins that are on, loaded.
    pub fn enabled(&self) -> Vec<Plugin> {
        self.installed()
            .iter()
            .filter(|i| i.enabled)
            .map(|i| self.load(i))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_file(path: &Path, text: &str) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, text).unwrap();
    }

    /// A marketplace with one plugin in it and one in a separate git repo.
    fn fixture(base: &Path) -> (PathBuf, PathBuf) {
        let market = base.join("market");
        write_file(
            &market.join(".evo-plugin/marketplace.json"),
            r#"{"name": "team", "owner": {"name": "Team"}, "plugins": [
                {"name": "notes", "source": "./plugins/notes", "description": "Notes"},
                {"name": "remote", "source": {"source": "url", "url": "REMOTE"}}
            ]}"#,
        );
        write_file(
            &market.join("plugins/notes/.evo-plugin/plugin.json"),
            r#"{"name": "notes", "version": "1.0.0"}"#,
        );
        write_file(
            &market.join("plugins/notes/commands/today.md"),
            "Write today's notes",
        );
        let remote = base.join("remote");
        write_file(
            &remote.join("skills/hello/SKILL.md"),
            "---\nname: hello\ndescription: Say hello\n---\nHi",
        );
        crate::git(&["init", "--quiet"], Some(&remote)).unwrap();
        crate::git(
            &["-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
            Some(&remote),
        )
        .unwrap();
        crate::git(
            &[
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "--quiet",
                "-m",
                "init",
            ],
            Some(&remote),
        )
        .unwrap();
        let text = std::fs::read_to_string(market.join(".evo-plugin/marketplace.json")).unwrap();
        let url = format!(
            "file:///{}",
            remote
                .to_string_lossy()
                .replace('\\', "/")
                .trim_start_matches('/')
        );
        write_file(
            &market.join(".evo-plugin/marketplace.json"),
            &text.replace("REMOTE", &url),
        );
        (market, remote)
    }

    #[test]
    fn folder_marketplace_install_enable_update_uninstall() {
        let dir = tempfile::tempdir().unwrap();
        let (market, _) = fixture(dir.path());
        let store = Store::new(dir.path().join("plugins"));
        let added = store.add_marketplace(&market.to_string_lossy()).unwrap();
        assert_eq!(added.name, "team");
        assert!(
            store.add_marketplace(&market.to_string_lossy()).is_err(),
            "added twice"
        );
        let catalog = store.catalog();
        assert_eq!(catalog.len(), 2);
        assert_eq!(catalog[0]["installed"], Value::Null);

        let notes = store.install("team", "notes").unwrap();
        assert_eq!(notes.id, "notes@team");
        assert_eq!(notes.version, "1.0.0");
        assert!(notes.path.join("commands/today.md").is_file());
        assert_eq!(store.enabled().len(), 1);
        assert_eq!(store.enabled()[0].commands.len(), 1);

        store.set_enabled("notes@team", false).unwrap();
        assert!(store.enabled().is_empty());
        let mut config = Map::new();
        config.insert("k".into(), json!("v"));
        store.set_config("notes@team", config).unwrap();
        // Reinstalling keeps on/off and settings.
        let again = store.update("notes@team").unwrap();
        assert!(!again.enabled);
        assert_eq!(again.config["k"], "v");

        store.uninstall("notes@team").unwrap();
        assert!(store.installed().is_empty());
        assert!(!notes.path.exists());
        store.remove_marketplace("team").unwrap();
        assert!(store.marketplaces().is_empty());
        assert!(market.exists(), "a folder marketplace is not deleted");
    }

    #[test]
    fn git_sources_clone_and_folders_install_in_place() {
        let dir = tempfile::tempdir().unwrap();
        let (market, remote) = fixture(dir.path());
        // The marketplace itself from git.
        crate::git(&["init", "--quiet"], Some(&market)).unwrap();
        crate::git(
            &["-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
            Some(&market),
        )
        .unwrap();
        crate::git(
            &[
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "--quiet",
                "-m",
                "m",
            ],
            Some(&market),
        )
        .unwrap();
        let url = format!(
            "file:///{}",
            market
                .to_string_lossy()
                .replace('\\', "/")
                .trim_start_matches('/')
        );
        let store = Store::new(dir.path().join("plugins"));
        let added = store.add_marketplace(&url).unwrap();
        assert!(added.location.starts_with(store.root()));
        // A plugin from its own git repository: versioned by commit.
        let remote_plugin = store.install("team", "remote").unwrap();
        assert_eq!(remote_plugin.version.len(), 12);
        assert!(remote_plugin.path.join("skills/hello/SKILL.md").is_file());
        assert_eq!(store.enabled()[0].skills.len(), 1);
        // A folder used in place.
        let local = store.install_folder(&remote).unwrap();
        assert_eq!(local.id, "remote@local");
        assert_eq!(local.path, remote);
        store.uninstall("remote@local").unwrap();
        assert!(remote.exists(), "a folder plugin is not deleted");
        store.remove_marketplace("team").unwrap();
        assert!(!added.location.exists());
    }
}
