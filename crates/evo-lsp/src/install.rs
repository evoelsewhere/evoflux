//! Finding and installing language servers.
//!
//! Managed installs live in `<lsp dir>/<server id>/` (the engine passes
//! `<agent dir>/lsp`); a server already on PATH is used as it is. rustup
//! installs into the toolchain. Installers run the language's own tool (npm,
//! go, dotnet, gem, rustup) or download the latest GitHub release.

use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::Serialize;

use crate::catalog::{Install, Server};

const INSTALL_TIMEOUT: Duration = Duration::from_secs(15 * 60);
/// Records where a downloaded server's binary is, inside its folder.
const BIN_RECORD: &str = ".evo-bin";

/// An executable on PATH (with Windows' extensions).
pub fn which(name: &str) -> Option<PathBuf> {
    let paths = std::env::var_os("PATH")?;
    let exts: Vec<String> = if cfg!(windows) {
        let pathext = std::env::var("PATHEXT").unwrap_or_else(|_| ".EXE;.CMD;.BAT;.COM".into());
        std::iter::once(String::new()).chain(pathext.split(';').map(|e| e.to_ascii_lowercase())).collect()
    } else {
        vec![String::new()]
    };
    for dir in std::env::split_paths(&paths) {
        for ext in &exts {
            let candidate = dir.join(format!("{name}{ext}"));
            if candidate.is_file() && (cfg!(windows) && !ext.is_empty() || !cfg!(windows)) {
                return Some(candidate);
            }
        }
    }
    None
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Located {
    pub path: PathBuf,
    /// `managed` (installed by evo), `path` (found on PATH), `toolchain`
    /// (rustup) or `editor` (shipped with a VS Code-style editor extension).
    pub source: &'static str,
}

fn exe(name: &str) -> String {
    if cfg!(windows) {
        format!("{name}.exe")
    } else {
        name.to_string()
    }
}

fn managed(server: &Server, lsp_dir: &Path) -> Option<PathBuf> {
    let dir = lsp_dir.join(server.id);
    let candidates: Vec<PathBuf> = match &server.install {
        Install::Npm { .. } => {
            let bin = dir.join("node_modules").join(".bin");
            vec![bin.join(format!("{}.cmd", server.command)), bin.join(server.command)]
        }
        Install::Go { .. } => vec![dir.join("bin").join(exe(server.command))],
        Install::Dotnet { .. } => vec![dir.join(exe(server.command))],
        Install::Gem { .. } => {
            let bin = dir.join("bin");
            vec![bin.join(format!("{}.bat", server.command)), bin.join(server.command)]
        }
        Install::GithubRelease { .. } => std::fs::read_to_string(dir.join(BIN_RECORD))
            .ok()
            .map(|p| vec![PathBuf::from(p.trim())])
            .unwrap_or_default(),
        Install::Rustup { .. } | Install::System { .. } => Vec::new(),
    };
    candidates.into_iter().find(|p| {
        p.is_file() && (cfg!(windows) || !p.extension().is_some_and(|e| e == "cmd" || e == "bat"))
    })
}

/// Editor extensions that ship a server: (extension folder prefix, path inside).
fn editor_bundles(server: &Server) -> &'static [(&'static str, &'static str)] {
    match server.id {
        "rust-analyzer" => &[("rust-lang.rust-analyzer-", "server/rust-analyzer")],
        _ => &[],
    }
}

/// A server that came with an editor extension (VS Code and its forks).
fn in_editor(server: &Server) -> Option<PathBuf> {
    let bundles = editor_bundles(server);
    if bundles.is_empty() {
        return None;
    }
    let home = std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")).map(PathBuf::from)?;
    let mut found: Vec<PathBuf> = Vec::new();
    for editor in [".vscode", ".vscode-insiders", ".cursor", ".windsurf"] {
        let Ok(entries) = std::fs::read_dir(home.join(editor).join("extensions")) else { continue };
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            for (prefix, inner) in bundles {
                if name.starts_with(prefix) {
                    let candidate = entry.path().join(exe(inner));
                    if candidate.is_file() {
                        found.push(candidate);
                    }
                }
            }
        }
    }
    // The newest extension version.
    found.sort();
    found.pop()
}

/// Where the server is, if it is anywhere.
pub fn locate(server: &Server, lsp_dir: &Path) -> Option<Located> {
    if let Some(path) = managed(server, lsp_dir) {
        return Some(Located { path, source: "managed" });
    }
    let editor = || in_editor(server).map(|path| Located { path, source: "editor" });
    if let Install::Rustup { component } = &server.install {
        // `~/.cargo/bin/rust-analyzer` is a rustup proxy even when the
        // component is missing: ask rustup where the real one is.
        let out = std::process::Command::new("rustup").args(["which", component]).output().ok()?;
        if out.status.success() {
            let path = PathBuf::from(String::from_utf8_lossy(&out.stdout).trim());
            if path.is_file() {
                return Some(Located { path, source: "toolchain" });
            }
        }
        return editor();
    }
    which(server.command).map(|path| Located { path, source: "path" }).or_else(editor)
}

/// Environment the server needs to run (gems find their home).
pub fn env_for(server: &Server, lsp_dir: &Path) -> Vec<(String, String)> {
    match &server.install {
        Install::Gem { .. } => {
            let dir = lsp_dir.join(server.id).to_string_lossy().into_owned();
            vec![("GEM_HOME".into(), dir.clone()), ("GEM_PATH".into(), dir)]
        }
        _ => Vec::new(),
    }
}

/// Which of the programs servers need are present.
pub fn missing_requirements(server: &Server) -> Vec<&'static str> {
    server.requires.iter().copied().filter(|tool| which(tool).is_none()).collect()
}

fn command(program: &str) -> tokio::process::Command {
    // npm, gem and friends are `.cmd` scripts on Windows.
    let resolved = which(program).map(|p| p.into_os_string()).unwrap_or_else(|| program.into());
    let mut cmd = tokio::process::Command::new(resolved);
    cmd.stdin(std::process::Stdio::null()).kill_on_drop(true);
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

async fn run(mut cmd: tokio::process::Command, what: &str, log: &(dyn Fn(String) + Send + Sync)) -> Result<(), String> {
    log(format!("$ {what}"));
    let out = tokio::time::timeout(INSTALL_TIMEOUT, cmd.output())
        .await
        .map_err(|_| format!("`{what}` took longer than {} minutes", INSTALL_TIMEOUT.as_secs() / 60))?
        .map_err(|e| format!("`{what}` could not start: {e}"))?;
    let text = format!("{}{}", String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr));
    let tail: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    let tail = tail[tail.len().saturating_sub(15)..].join("\n");
    if !tail.is_empty() {
        log(tail.clone());
    }
    if out.status.success() {
        Ok(())
    } else {
        Err(format!("`{what}` failed ({}):\n{tail}", out.status))
    }
}

fn platform() -> (&'static str, &'static str) {
    let os = match std::env::consts::OS {
        "macos" => "macos",
        "windows" => "windows",
        _ => "linux",
    };
    (os, std::env::consts::ARCH)
}

/// Find `name` (or `name.exe`, `.bat`, `.cmd`) under `dir`.
fn find_binary(dir: &Path, name: &str, depth: usize) -> Option<PathBuf> {
    let wanted: Vec<String> = if cfg!(windows) {
        vec![format!("{name}.exe"), format!("{name}.bat"), format!("{name}.cmd")]
    } else {
        vec![name.to_string()]
    };
    let mut dirs = vec![(dir.to_path_buf(), 0usize)];
    while let Some((d, level)) = dirs.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else { continue };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                if level < depth {
                    dirs.push((path, level + 1));
                }
            } else if entry
                .file_name()
                .to_str()
                .is_some_and(|n| wanted.iter().any(|w| w.eq_ignore_ascii_case(n)))
            {
                return Some(path);
            }
        }
    }
    None
}

const DOWNLOAD_ATTEMPTS: u32 = 3;

/// A network error in words, without the request URL: GitHub's asset links
/// are long signed URLs that bury the cause. Includes the underlying cause
/// (a timeout, a reset connection), which reqwest's own message leaves out.
fn net_error(e: reqwest::Error) -> String {
    let e = e.without_url();
    if let Some(status) = e.status() {
        return format!("the server answered {status}");
    }
    let mut text = if e.is_timeout() {
        "the connection stalled".to_string()
    } else if e.is_connect() {
        "could not connect".to_string()
    } else if e.is_body() || e.is_decode() {
        "the connection broke off mid-download".to_string()
    } else {
        e.to_string()
    };
    // The innermost cause says what actually happened.
    let mut cause = String::new();
    let mut source = std::error::Error::source(&e);
    while let Some(err) = source {
        let message = err.to_string();
        if !message.is_empty() {
            cause = message;
        }
        source = err.source();
    }
    if !cause.is_empty() {
        text.push_str(&format!(" ({cause})"));
    }
    text
}

/// One attempt at fetching `url` whole.
async fn download(client: &reqwest::Client, url: &str) -> Result<Vec<u8>, String> {
    let mut response = client.get(url).send().await.and_then(|r| r.error_for_status()).map_err(net_error)?;
    let mut bytes = Vec::with_capacity(response.content_length().unwrap_or(0).min(256 << 20) as usize);
    while let Some(chunk) = response.chunk().await.map_err(net_error)? {
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

async fn github_release(
    server: &Server,
    repo: &str,
    assets: &[crate::catalog::Asset],
    dir: &Path,
    log: &(dyn Fn(String) + Send + Sync),
) -> Result<PathBuf, String> {
    let (os, arch) = platform();
    let asset = assets
        .iter()
        .find(|a| (a.os.is_empty() || a.os == os) && (a.arch.is_empty() || a.arch == arch))
        .ok_or_else(|| format!("no {} build for {os} {arch}", server.name))?;
    let client = reqwest::Client::builder()
        .user_agent(concat!("evo/", env!("CARGO_PKG_VERSION")))
        .connect_timeout(Duration::from_secs(30))
        // A stall, not a slow connection, fails the download.
        .read_timeout(Duration::from_secs(60))
        .build()
        .map_err(net_error)?;
    log(format!("Looking up the latest release of {repo}"));
    let release: serde_json::Value = client
        .get(format!("https://api.github.com/repos/{repo}/releases/latest"))
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
        .and_then(|r| r.error_for_status())
        .map_err(|e| format!("GitHub could not be reached: {}", net_error(e)))?
        .json()
        .await
        .map_err(|e| format!("GitHub sent an unreadable answer: {}", net_error(e)))?;
    let tag = release.get("tag_name").and_then(|v| v.as_str()).unwrap_or("latest").to_string();
    let found = release
        .get("assets")
        .and_then(|a| a.as_array())
        .into_iter()
        .flatten()
        .find(|a| {
            let name = a.get("name").and_then(|n| n.as_str()).unwrap_or("");
            asset.contains.iter().all(|part| name.contains(part))
        })
        .ok_or_else(|| format!("release {tag} of {repo} has no asset matching {:?}", asset.contains))?;
    let name = found.get("name").and_then(|n| n.as_str()).unwrap_or("download").to_string();
    let url = found
        .get("browser_download_url")
        .and_then(|u| u.as_str())
        .ok_or("the asset has no download URL")?;
    log(format!("Downloading {name} ({tag})"));
    let mut attempt = 1;
    let bytes = loop {
        match download(&client, url).await {
            Ok(bytes) => break bytes,
            Err(e) if attempt < DOWNLOAD_ATTEMPTS => {
                attempt += 1;
                log(format!("{e} — retrying ({attempt} of {DOWNLOAD_ATTEMPTS})"));
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
            Err(e) => return Err(format!("Downloading {name} failed: {e}")),
        }
    };
    log(format!("Downloaded {:.1} MB", bytes.len() as f64 / 1_048_576.0));
    let _ = std::fs::remove_dir_all(dir);
    std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    let target = dir.to_path_buf();
    let lower = name.to_ascii_lowercase();
    let command = server.command.to_string();
    tokio::task::spawn_blocking(move || -> Result<(), String> {
        if lower.ends_with(".zip") {
            let mut archive = zip::ZipArchive::new(std::io::Cursor::new(bytes)).map_err(|e| e.to_string())?;
            archive.extract(&target).map_err(|e| e.to_string())
        } else if lower.ends_with(".tar.gz") || lower.ends_with(".tgz") {
            let decoder = flate2::read::GzDecoder::new(std::io::Cursor::new(bytes));
            tar::Archive::new(decoder).unpack(&target).map_err(|e| e.to_string())
        } else {
            // A bare binary.
            let file = target.join(exe(&command));
            std::fs::write(&file, &bytes).map_err(|e| e.to_string())?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o755));
            }
            Ok(())
        }
    })
    .await
    .map_err(|e| e.to_string())??;
    let binary = find_binary(dir, server.command, 4)
        .ok_or_else(|| format!("{} was not found in {name}", server.command))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o755));
    }
    std::fs::write(dir.join(BIN_RECORD), binary.to_string_lossy().as_bytes()).map_err(|e| e.to_string())?;
    Ok(binary)
}

/// Install `server`; `log` gets progress lines. Returns where it is.
pub async fn install(server: &Server, lsp_dir: &Path, log: &(dyn Fn(String) + Send + Sync)) -> Result<Located, String> {
    let missing = missing_requirements(server);
    if !missing.is_empty() && !matches!(server.install, Install::System { .. }) {
        return Err(format!("{} needs {} on this computer first", server.name, missing.join(" and ")));
    }
    let dir = lsp_dir.join(server.id);
    match &server.install {
        Install::Npm { packages } => {
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
            let mut cmd = command("npm");
            cmd.arg("install").arg("--prefix").arg(&dir).args(["--no-audit", "--no-fund", "--loglevel=error"]);
            cmd.args(packages.iter());
            run(cmd, &format!("npm install {}", packages.join(" ")), log).await?;
        }
        Install::Go { module } => {
            std::fs::create_dir_all(dir.join("bin")).map_err(|e| e.to_string())?;
            let mut cmd = command("go");
            cmd.args(["install", &format!("{module}@latest")]).env("GOBIN", dir.join("bin"));
            run(cmd, &format!("go install {module}@latest"), log).await?;
        }
        Install::Rustup { component } => {
            let mut cmd = command("rustup");
            cmd.args(["component", "add", component]);
            run(cmd, &format!("rustup component add {component}"), log).await?;
        }
        Install::Dotnet { tool } => {
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
            let verb = if managed(server, lsp_dir).is_some() { "update" } else { "install" };
            let mut cmd = command("dotnet");
            cmd.args(["tool", verb, tool, "--tool-path"]).arg(&dir);
            run(cmd, &format!("dotnet tool {verb} {tool}"), log).await?;
        }
        Install::Gem { gem } => {
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
            let mut cmd = command("gem");
            cmd.args(["install", gem, "--no-document", "--install-dir"]).arg(&dir).arg("--bindir").arg(dir.join("bin"));
            run(cmd, &format!("gem install {gem}"), log).await?;
        }
        Install::GithubRelease { repo, assets } => {
            github_release(server, repo, assets, &dir, log).await?;
        }
        Install::System { hint } => return Err(hint.to_string()),
    }
    let located = locate(server, lsp_dir).ok_or_else(|| format!("{} installed, but {} was not found", server.name, server.command))?;
    log(format!("Ready: {}", located.path.display()));
    Ok(located)
}

/// Remove evo's own install of `server` (not one on PATH or in a toolchain).
pub fn uninstall(server: &Server, lsp_dir: &Path) -> Result<(), String> {
    let dir = lsp_dir.join(server.id);
    if !dir.exists() {
        return Err(match server.install {
            Install::Rustup { component } => format!("installed with rustup: `rustup component remove {component}`"),
            _ => format!("{} was not installed by evo", server.name),
        });
    }
    std::fs::remove_dir_all(&dir).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn binaries_are_found_in_unpacked_folders() {
        let dir = tempfile::tempdir().unwrap();
        let nested = dir.path().join("clangd_19/bin");
        std::fs::create_dir_all(&nested).unwrap();
        let name = if cfg!(windows) { "clangd.exe" } else { "clangd" };
        std::fs::write(nested.join(name), "").unwrap();
        assert_eq!(find_binary(dir.path(), "clangd", 4), Some(nested.join(name)));
        assert_eq!(find_binary(dir.path(), "gopls", 4), None);
    }

    #[test]
    fn missing_programs_are_reported() {
        let server = crate::catalog::find("typescript").unwrap();
        // Whatever this machine has, the answer only lists required programs.
        for tool in missing_requirements(server) {
            assert!(server.requires.contains(&tool));
        }
    }
}
