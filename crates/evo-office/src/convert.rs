//! Headless Office-to-PDF conversion with the installed LibreOffice runtime.
//!
//! Conversions share one hardened user profile (macros disabled, untrusted
//! remote references blocked, external links never refreshed) and are
//! serialized, because a LibreOffice profile can only be used by one process at
//! a time. A conversion that exceeds its timeout has its whole process tree
//! killed.

use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use crate::install::Runtime;
use crate::Error;

/// Default time a single conversion may take.
pub const CONVERSION_TIMEOUT: Duration = Duration::from_secs(180);
/// What LibreOffice exits with when it initialised a fresh profile instead of converting.
const RESTART_REQUIRED: i32 = 81;

const PROFILE_SETTINGS: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry"
 xmlns:xs="http://www.w3.org/2001/XMLSchema"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>1</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
"#;

/// The LibreOffice PDF export filter for a file extension (without the dot), or
/// `None` when the runtime does not convert it. Workbooks export one page per
/// sheet so a sheet reads as a whole instead of being cut into print pages.
pub fn export_filter(extension: &str) -> Option<&'static str> {
    match extension.to_ascii_lowercase().as_str() {
        "docx" | "doc" | "odt" | "rtf" | "dotx" => Some("pdf:writer_pdf_Export"),
        "pptx" | "ppt" | "odp" | "ppsx" => Some("pdf:impress_pdf_Export"),
        "xlsx" | "xls" | "ods" => {
            Some(r#"pdf:calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}"#)
        }
        _ => None,
    }
}

/// Whether [`Runtime::convert_to_pdf`] accepts a file with this extension.
pub fn supports(extension: &str) -> bool {
    export_filter(extension).is_some()
}

impl Runtime {
    fn profile_dir(&self) -> Result<PathBuf, Error> {
        let profile = self.home().join("profile");
        let user = profile.join("user");
        std::fs::create_dir_all(&user)?;
        let settings = user.join("registrymodifications.xcu");
        if !settings.exists() {
            std::fs::write(settings, PROFILE_SETTINGS)?;
        }
        Ok(profile)
    }

    /// Convert `source` to PDF inside `workdir` and return the PDF's path.
    pub async fn convert_to_pdf(
        &self,
        source: &Path,
        workdir: &Path,
        timeout: Duration,
    ) -> Result<PathBuf, Error> {
        let runtime = self.installed().ok_or(Error::NotInstalled)?;
        let extension = source
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let filter = export_filter(&extension).ok_or_else(|| {
            Error::Convert(format!(".{extension} cannot be converted by the runtime."))
        })?;
        tokio::fs::create_dir_all(workdir).await?;
        // A fixed ASCII name keeps LibreOffice away from awkward user file names
        // and makes the output name predictable.
        let staged = workdir.join(format!("document.{extension}"));
        tokio::fs::copy(source, &staged).await?;
        let output = workdir.join("pdf");
        tokio::fs::create_dir_all(&output).await?;
        let profile = self.profile_dir()?;
        let profile_url = url::Url::from_directory_path(&profile)
            .map_err(|_| Error::Convert("The profile folder is not an absolute path.".into()))?;
        let pdf = output.join("document.pdf");

        let _guard = self.inner.convert.lock().await;
        let mut last = (0, String::new());
        for _attempt in 0..2 {
            last = run(
                &runtime.executable,
                &profile_url,
                filter,
                &output,
                &staged,
                timeout,
            )
            .await?;
            // A fresh profile makes LibreOffice initialise it and exit without
            // converting: code 81 on Linux/macOS, a silent 0 on Windows. The
            // second run, on the initialised profile, converts.
            let converted = std::fs::metadata(&pdf)
                .map(|m| m.len() > 0)
                .unwrap_or(false);
            if converted || !matches!(last.0, 0 | RESTART_REQUIRED) {
                break;
            }
        }
        let converted = std::fs::metadata(&pdf)
            .map(|m| m.len() > 0)
            .unwrap_or(false);
        if last.0 != 0 || !converted {
            let detail: String = last
                .1
                .trim()
                .chars()
                .rev()
                .take(400)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect();
            tracing::warn!(file = ?source.file_name(), code = last.0, %detail, "office conversion failed");
            return Err(Error::Convert(
                format!("LibreOffice could not convert this document. {detail}")
                    .trim()
                    .into(),
            ));
        }
        Ok(pdf)
    }
}

async fn run(
    executable: &Path,
    profile_url: &url::Url,
    filter: &str,
    output: &Path,
    staged: &Path,
    timeout: Duration,
) -> Result<(i32, String), Error> {
    let mut command = tokio::process::Command::new(executable);
    command
        .args([
            "--headless",
            "--invisible",
            "--norestore",
            "--nolockcheck",
            "--nologo",
            "--nodefault",
        ])
        .arg(format!("-env:UserInstallation={profile_url}"))
        .args(["--convert-to", filter, "--outdir"])
        .arg(output)
        .arg(staged)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    if cfg!(target_os = "linux") {
        // No display server on most Linux hosts.
        command.env("SAL_USE_VCLPLUGIN", "svp");
    }
    #[cfg(windows)]
    command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    #[cfg(unix)]
    command.process_group(0);
    let mut child = command
        .spawn()
        .map_err(|e| Error::Convert(format!("Could not start LibreOffice: {e}")))?;
    let pid = child.id();
    let mut stderr = child.stderr.take();
    let collect = tokio::spawn(async move {
        let mut text = Vec::new();
        if let Some(pipe) = stderr.as_mut() {
            let _ = tokio::io::AsyncReadExt::read_to_end(pipe, &mut text).await;
        }
        String::from_utf8_lossy(&text).into_owned()
    });
    match tokio::time::timeout(timeout, child.wait()).await {
        Ok(status) => {
            let status = status?;
            let text = collect.await.unwrap_or_default();
            Ok((status.code().unwrap_or(-1), text))
        }
        Err(_) => {
            // Kill the tree while its root is still alive: afterwards the
            // children can no longer be found through it.
            if let Some(pid) = pid {
                kill_tree(pid).await;
            }
            let _ = child.kill().await;
            collect.abort();
            Err(Error::Timeout(timeout.as_secs()))
        }
    }
}

/// Kill a process and everything it started.
async fn kill_tree(pid: u32) {
    #[cfg(windows)]
    let mut command = {
        let mut c = tokio::process::Command::new("taskkill");
        c.args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(0x0800_0000);
        c
    };
    #[cfg(unix)]
    let mut command = {
        let mut c = tokio::process::Command::new("kill");
        c.args(["-KILL", "--", &format!("-{pid}")]);
        c
    };
    let _ = command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .await;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filters_follow_the_document_family() {
        assert!(export_filter("DOCX").unwrap().contains("writer"));
        assert!(export_filter("ppt").unwrap().contains("impress"));
        assert!(export_filter("xls").unwrap().contains("SinglePageSheets"));
        assert!(export_filter("exe").is_none());
        assert!(supports("odt") && !supports("txt"));
    }
}
