//! "Open in": the apps on this machine that can open a workspace folder (the
//! file manager, code editors, terminals), each with its own icon.
//!
//! Detection looks for known install locations and the commands on `PATH`;
//! nothing is hardcoded as present. Icons come from the OS (the shell image
//! factory on Windows, NSWorkspace on macOS, the icon theme on Linux) and
//! reach the UI as PNG/SVG data URLs. The list is built once per run.

use std::path::{Path, PathBuf};
use std::process::Command;

use serde::Serialize;
use tauri::State;
use tokio::sync::OnceCell;

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum AppKind {
    FileManager,
    Editor,
    Terminal,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OpenApp {
    pub id: String,
    pub name: String,
    pub kind: AppKind,
    /// Data URL of the app's own icon; `None` lets the UI draw a glyph.
    pub icon: Option<String>,
    #[serde(skip)]
    launch: Launch,
}

/// How to open a folder in an app: run `program` with `args`, where `{path}`
/// in an argument becomes the folder.
#[derive(Clone)]
struct Launch {
    program: PathBuf,
    args: Vec<String>,
    /// Start the process in the folder (terminals without a directory flag).
    in_dir: bool,
    /// Console programs get a console window of their own (Windows).
    new_console: bool,
}

impl Launch {
    fn new(program: impl Into<PathBuf>, args: &[&str]) -> Self {
        Self {
            program: program.into(),
            args: args.iter().map(|a| a.to_string()).collect(),
            in_dir: false,
            new_console: false,
        }
    }

    fn in_dir(mut self) -> Self {
        self.in_dir = true;
        self
    }

    #[allow(dead_code)]
    fn console(mut self) -> Self {
        self.new_console = true;
        self
    }

    fn spawn(&self, folder: &Path) -> std::io::Result<()> {
        let folder_str = folder.to_string_lossy();
        let mut command = Command::new(&self.program);
        command.args(self.args.iter().map(|a| a.replace("{path}", &folder_str)));
        if self.in_dir {
            command.current_dir(folder);
        }
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NEW_CONSOLE: u32 = 0x0000_0010;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            // GUI apps get no console window of ours flashing up.
            command.creation_flags(if self.new_console { CREATE_NEW_CONSOLE } else { CREATE_NO_WINDOW });
        }
        let mut child = command.spawn()?;
        // Reap the launcher so it does not linger as a zombie (Unix).
        std::thread::spawn(move || {
            let _ = child.wait();
        });
        Ok(())
    }
}

/// One app found on this machine, before its icon is read.
struct Found {
    id: String,
    name: String,
    kind: AppKind,
    /// The file the OS draws the app's icon from (exe, .app bundle, or an
    /// icon file on Linux).
    icon_source: Option<PathBuf>,
    launch: Launch,
}

#[derive(Default)]
pub struct AppsState(OnceCell<Vec<OpenApp>>);

impl AppsState {
    async fn apps(&self) -> &Vec<OpenApp> {
        self.0
            .get_or_init(|| async {
                tauri::async_runtime::spawn_blocking(detect)
                    .await
                    .unwrap_or_default()
            })
            .await
    }
}

/// Apps that can open a folder, file manager first, then editors, then
/// terminals.
#[tauri::command]
pub async fn open_apps(state: State<'_, AppsState>) -> Result<Vec<OpenApp>, String> {
    Ok(state.apps().await.clone())
}

/// Open `path` in the app `id` from [`open_apps`].
#[tauri::command]
pub async fn open_in_app(state: State<'_, AppsState>, id: String, path: String) -> Result<(), String> {
    let folder = PathBuf::from(&path);
    if !folder.exists() {
        return Err(format!("{path} does not exist"));
    }
    let app = state
        .apps()
        .await
        .iter()
        .find(|app| app.id == id)
        .ok_or_else(|| format!("no app {id}"))?;
    app.launch
        .spawn(&folder)
        .map_err(|error| format!("could not open {}: {error}", app.name))
}

fn detect() -> Vec<OpenApp> {
    let mut found = platform::find();
    found.sort_by_key(|app| match app.kind {
        AppKind::FileManager => 0,
        AppKind::Editor => 1,
        AppKind::Terminal => 2,
    });
    // One entry per id: the first location found wins.
    let mut seen = std::collections::HashSet::new();
    found.retain(|app| seen.insert(app.id.clone()));

    found
        .into_iter()
        .map(|app| OpenApp {
            icon: app.icon_source.as_deref().and_then(platform::icon),
            id: app.id,
            name: app.name,
            kind: app.kind,
            launch: app.launch,
        })
        .collect()
}

/// The first file named one of `names` in a `PATH` directory.
fn on_path(names: &[&str]) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path).find_map(|dir| {
        names
            .iter()
            .map(|name| dir.join(name))
            .find(|candidate| candidate.is_file())
    })
}

fn first_existing(candidates: impl IntoIterator<Item = PathBuf>) -> Option<PathBuf> {
    candidates.into_iter().find(|path| path.exists())
}

// 64px covers a 16–32px glyph on high-DPI screens.
#[cfg(any(target_os = "windows", target_os = "macos"))]
const ICON_SIZE: u16 = 64;

/// RGBA pixels as a PNG data URL; `None` for an empty or malformed image.
#[cfg(any(target_os = "windows", target_os = "macos"))]
fn png_data_url(width: u32, height: u32, rgba: &[u8]) -> Option<String> {
    use base64::{engine::general_purpose::STANDARD, Engine};

    if rgba.len() != (width * height * 4) as usize || rgba.iter().all(|&b| b == 0) {
        return None;
    }
    let mut png = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut png, width, height);
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        let mut writer = encoder.write_header().ok()?;
        writer.write_image_data(rgba).ok()?;
    }
    Some(format!("data:image/png;base64,{}", STANDARD.encode(png)))
}

#[cfg(target_os = "windows")]
mod platform {
    use super::*;

    /// The shell's icon for a file path or a shell parsing name such as
    /// `shell:AppsFolder\<AUMID>` (packaged apps, whose `WindowsApps` alias
    /// only carries a generic icon).
    pub fn icon(source: &Path) -> Option<String> {
        use windows::core::HSTRING;
        use windows::Win32::Foundation::SIZE;
        use windows::Win32::Graphics::Gdi::DeleteObject;
        use windows::Win32::Graphics::Imaging::{
            CLSID_WICImagingFactory, GUID_WICPixelFormat32bppBGRA, GUID_WICPixelFormat32bppRGBA, IWICImagingFactory,
            WICBitmapUseAlpha, WICRect,
        };
        use windows::Win32::System::Com::{CoCreateInstance, CoInitialize, CoUninitialize, CLSCTX_ALL};
        use windows::Win32::UI::Shell::{IShellItemImageFactory, SHCreateItemFromParsingName, SIIGBF_ICONONLY, SIIGBF_SCALEUP};

        struct Com(bool);
        impl Drop for Com {
            fn drop(&mut self) {
                if self.0 {
                    unsafe { CoUninitialize() };
                }
            }
        }
        let _com = Com(unsafe { CoInitialize(None) }.is_ok());

        let size = i32::from(ICON_SIZE);
        let name = HSTRING::from(source.as_os_str());
        let factory: IShellItemImageFactory = unsafe { SHCreateItemFromParsingName(&name, None) }.ok()?;
        let hbitmap = unsafe { factory.GetImage(SIZE { cx: size, cy: size }, SIIGBF_ICONONLY | SIIGBF_SCALEUP) }.ok()?;
        let pixels = (|| {
            let wic: IWICImagingFactory = unsafe { CoCreateInstance(&CLSID_WICImagingFactory, None, CLSCTX_ALL) }.ok()?;
            let bitmap = unsafe { wic.CreateBitmapFromHBITMAP(hbitmap, None, WICBitmapUseAlpha) }.ok()?;
            let format = unsafe { bitmap.GetPixelFormat() }.ok()?;
            if format != GUID_WICPixelFormat32bppBGRA && format != GUID_WICPixelFormat32bppRGBA {
                return None;
            }
            let mut pixels = vec![0u8; (size * size * 4) as usize];
            let rect = WICRect { X: 0, Y: 0, Width: size, Height: size };
            unsafe { bitmap.CopyPixels(&rect, (size * 4) as u32, &mut pixels) }.ok()?;
            if format == GUID_WICPixelFormat32bppBGRA {
                pixels.chunks_exact_mut(4).for_each(|px| px.swap(0, 2));
            }
            Some(pixels)
        })();
        unsafe {
            let _ = DeleteObject(hbitmap);
        }
        png_data_url(size as u32, size as u32, &pixels?)
    }

    /// A packaged app's shell name, when it is installed.
    fn packaged(aumids: &[&str]) -> Option<PathBuf> {
        aumids
            .iter()
            .map(|aumid| PathBuf::from(format!(r"shell:AppsFolder\{aumid}")))
            .find(|name| icon(name).is_some())
    }

    fn env_dir(name: &str) -> Option<PathBuf> {
        std::env::var_os(name).map(PathBuf::from)
    }

    /// An editor's exe: known install folders, or found from its `PATH`
    /// launcher (`<root>\bin\code.cmd`, `<root>\resources\app\bin\cursor.cmd`).
    fn editor_exe(dirs: &[&str], exe: &str, launchers: &[&str]) -> Option<PathBuf> {
        let roots = [env_dir("LOCALAPPDATA").map(|d| d.join("Programs")), env_dir("ProgramFiles"), env_dir("ProgramFiles(x86)")];
        let installed = roots
            .iter()
            .flatten()
            .flat_map(|root| dirs.iter().map(move |dir| root.join(dir).join(exe)));
        first_existing(installed).or_else(|| {
            let launcher = on_path(launchers)?;
            launcher.ancestors().skip(1).take(4).map(|dir| dir.join(exe)).find(|p| p.is_file())
        })
    }

    pub fn find() -> Vec<Found> {
        let mut apps = Vec::new();
        let windir = env_dir("WINDIR").unwrap_or_else(|| PathBuf::from(r"C:\Windows"));

        let explorer = windir.join("explorer.exe");
        apps.push(Found {
            id: "file-manager".into(),
            name: "File Explorer".into(),
            kind: AppKind::FileManager,
            icon_source: Some(explorer.clone()),
            launch: Launch::new(explorer, &["{path}"]),
        });

        let editors: &[(&str, &str, &[&str], &str, &[&str])] = &[
            ("vscode", "VS Code", &["Microsoft VS Code"], "Code.exe", &["code.cmd"]),
            ("vscode-insiders", "VS Code Insiders", &["Microsoft VS Code Insiders"], "Code - Insiders.exe", &["code-insiders.cmd"]),
            ("cursor", "Cursor", &["cursor", "Cursor"], "Cursor.exe", &["cursor.cmd"]),
            ("windsurf", "Windsurf", &["Windsurf"], "Windsurf.exe", &["windsurf.cmd"]),
            ("zed", "Zed", &["Zed"], "Zed.exe", &[]),
            ("sublime", "Sublime Text", &["Sublime Text", "Sublime Text 3"], "sublime_text.exe", &["subl.exe"]),
        ];
        for (id, name, dirs, exe, launchers) in editors {
            if let Some(exe) = editor_exe(dirs, exe, launchers) {
                apps.push(Found {
                    id: (*id).into(),
                    name: (*name).into(),
                    kind: AppKind::Editor,
                    icon_source: Some(exe.clone()),
                    launch: Launch::new(exe, &["{path}"]),
                });
            }
        }
        apps.extend(jetbrains());

        let apps_dir = env_dir("LOCALAPPDATA").map(|d| d.join(r"Microsoft\WindowsApps"));
        if let Some(wt) = apps_dir.map(|d| d.join("wt.exe")).filter(|p| p.exists()) {
            apps.push(Found {
                id: "windows-terminal".into(),
                name: "Windows Terminal".into(),
                kind: AppKind::Terminal,
                icon_source: packaged(&[
                    "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App",
                    "Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe!App",
                ]),
                launch: Launch::new(wt, &["-d", "{path}"]),
            });
        }
        let pwsh = first_existing(env_dir("ProgramFiles").map(|d| d.join(r"PowerShell\7\pwsh.exe")))
            .or_else(|| on_path(&["pwsh.exe"]));
        let powershell = pwsh
            .map(|exe| ("PowerShell", exe))
            .or_else(|| {
                let exe = windir.join(r"System32\WindowsPowerShell\v1.0\powershell.exe");
                exe.exists().then_some(("Windows PowerShell", exe))
            });
        if let Some((name, exe)) = powershell {
            apps.push(Found {
                id: "powershell".into(),
                name: name.into(),
                kind: AppKind::Terminal,
                icon_source: Some(exe.clone()),
                launch: Launch::new(exe, &["-NoLogo"]).in_dir().console(),
            });
        }
        let cmd = windir.join(r"System32\cmd.exe");
        if cmd.exists() {
            apps.push(Found {
                id: "cmd".into(),
                name: "Command Prompt".into(),
                kind: AppKind::Terminal,
                icon_source: Some(cmd.clone()),
                launch: Launch::new(cmd, &[]).in_dir().console(),
            });
        }
        let git_bash = first_existing(
            [env_dir("ProgramFiles"), env_dir("LOCALAPPDATA").map(|d| d.join("Programs"))]
                .into_iter()
                .flatten()
                .map(|d| d.join(r"Git\git-bash.exe")),
        );
        if let Some(exe) = git_bash {
            apps.push(Found {
                id: "git-bash".into(),
                name: "Git Bash".into(),
                kind: AppKind::Terminal,
                icon_source: Some(exe.clone()),
                launch: Launch::new(exe, &["--cd={path}"]),
            });
        }
        apps
    }

    /// JetBrains IDEs: `<root>\<IDE name>\bin\<ide>64.exe`, under Program
    /// Files\JetBrains (installer) or %LOCALAPPDATA%\Programs (Toolbox).
    fn jetbrains() -> Vec<Found> {
        const IDES: &[&str] = &[
            "idea64.exe", "pycharm64.exe", "webstorm64.exe", "goland64.exe", "rider64.exe",
            "clion64.exe", "rustrover64.exe", "phpstorm64.exe", "datagrip64.exe", "studio64.exe",
        ];
        let roots = [
            env_dir("ProgramFiles").map(|d| d.join("JetBrains")),
            env_dir("LOCALAPPDATA").map(|d| d.join("Programs")),
            env_dir("ProgramFiles").map(|d| d.join("Android")),
        ];
        let mut found = Vec::new();
        for root in roots.into_iter().flatten() {
            let Ok(entries) = std::fs::read_dir(&root) else { continue };
            let mut dirs: Vec<PathBuf> = entries.flatten().map(|e| e.path()).collect();
            // Newest version folder first, so the de-duplication keeps it.
            dirs.sort();
            dirs.reverse();
            for dir in dirs {
                let Some(exe) = IDES.iter().map(|exe| dir.join("bin").join(exe)).find(|p| p.is_file()) else {
                    continue;
                };
                let stem = exe.file_stem().map(|s| s.to_string_lossy().trim_end_matches("64").to_string()).unwrap_or_default();
                let name = dir.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| stem.clone());
                // "IntelliJ IDEA 2025.2" → "IntelliJ IDEA".
                let name = name
                    .split(' ')
                    .filter(|word| !word.starts_with(|c: char| c.is_ascii_digit()))
                    .collect::<Vec<_>>()
                    .join(" ");
                found.push(Found {
                    id: format!("jetbrains-{stem}"),
                    name,
                    kind: AppKind::Editor,
                    icon_source: Some(exe.clone()),
                    launch: Launch::new(exe, &["{path}"]),
                });
            }
        }
        found
    }
}

#[cfg(target_os = "macos")]
mod platform {
    use super::*;

    /// NSWorkspace's icon for an app bundle.
    pub fn icon(path: &Path) -> Option<String> {
        // The crate panics on pixel formats it does not know; that is no reason to fail the menu.
        let icon = std::panic::catch_unwind(|| file_icon_provider::get_file_icon(path, ICON_SIZE)).ok()?.ok()?;
        png_data_url(icon.width, icon.height, &icon.pixels)
    }

    /// `<name>.app` in /Applications, ~/Applications or a system folder.
    fn bundle(name: &str) -> Option<PathBuf> {
        let home = std::env::var_os("HOME").map(PathBuf::from);
        let roots = [
            Some(PathBuf::from("/Applications")),
            home.map(|h| h.join("Applications")),
            Some(PathBuf::from("/System/Applications")),
            Some(PathBuf::from("/System/Applications/Utilities")),
            Some(PathBuf::from("/Applications/Utilities")),
            Some(PathBuf::from("/System/Library/CoreServices")),
        ];
        first_existing(roots.into_iter().flatten().map(|root| root.join(format!("{name}.app"))))
    }

    fn open_with(app: &Path) -> Launch {
        Launch::new("/usr/bin/open", &["-a", &app.to_string_lossy(), "{path}"])
    }

    pub fn find() -> Vec<Found> {
        let mut apps = Vec::new();
        let finder = bundle("Finder").unwrap_or_else(|| PathBuf::from("/System/Library/CoreServices/Finder.app"));
        apps.push(Found {
            id: "file-manager".into(),
            name: "Finder".into(),
            kind: AppKind::FileManager,
            icon_source: Some(finder),
            launch: Launch::new("/usr/bin/open", &["{path}"]),
        });

        let known: &[(&str, &str, &str, AppKind)] = &[
            ("vscode", "VS Code", "Visual Studio Code", AppKind::Editor),
            ("vscode-insiders", "VS Code Insiders", "Visual Studio Code - Insiders", AppKind::Editor),
            ("cursor", "Cursor", "Cursor", AppKind::Editor),
            ("windsurf", "Windsurf", "Windsurf", AppKind::Editor),
            ("zed", "Zed", "Zed", AppKind::Editor),
            ("zed-preview", "Zed Preview", "Zed Preview", AppKind::Editor),
            ("sublime", "Sublime Text", "Sublime Text", AppKind::Editor),
            ("nova", "Nova", "Nova", AppKind::Editor),
            ("xcode", "Xcode", "Xcode", AppKind::Editor),
            ("android-studio", "Android Studio", "Android Studio", AppKind::Editor),
            ("terminal", "Terminal", "Terminal", AppKind::Terminal),
            ("iterm", "iTerm", "iTerm", AppKind::Terminal),
            ("warp", "Warp", "Warp", AppKind::Terminal),
            ("ghostty", "Ghostty", "Ghostty", AppKind::Terminal),
        ];
        for (id, name, bundle_name, kind) in known {
            if let Some(app) = bundle(bundle_name) {
                apps.push(Found {
                    id: (*id).into(),
                    name: (*name).into(),
                    kind: *kind,
                    icon_source: Some(app.clone()),
                    launch: open_with(&app),
                });
            }
        }

        // JetBrains IDEs carry an edition or version in the bundle name.
        const JETBRAINS: &[&str] = &[
            "IntelliJ IDEA", "PyCharm", "WebStorm", "GoLand", "Rider", "CLion", "RustRover", "PhpStorm", "DataGrip", "Fleet",
        ];
        if let Ok(entries) = std::fs::read_dir("/Applications") {
            let mut bundles: Vec<PathBuf> = entries.flatten().map(|e| e.path()).collect();
            bundles.sort();
            for app in bundles {
                let Some(stem) = app.file_stem().map(|s| s.to_string_lossy().to_string()) else { continue };
                let Some(ide) = JETBRAINS.iter().find(|ide| stem.starts_with(*ide)) else { continue };
                apps.push(Found {
                    id: format!("jetbrains-{}", ide.to_lowercase().replace(' ', "-")),
                    name: stem.clone(),
                    kind: AppKind::Editor,
                    icon_source: Some(app.clone()),
                    launch: open_with(&app),
                });
            }
        }
        apps
    }
}

#[cfg(all(unix, not(target_os = "macos")))]
mod platform {
    use super::*;
    use base64::{engine::general_purpose::STANDARD, Engine};

    fn data_dirs() -> Vec<PathBuf> {
        let home = std::env::var_os("HOME").map(PathBuf::from);
        let mut dirs: Vec<PathBuf> = home.iter().map(|h| h.join(".local/share")).collect();
        let system = std::env::var("XDG_DATA_DIRS").unwrap_or_else(|_| "/usr/local/share:/usr/share".into());
        dirs.extend(system.split(':').filter(|d| !d.is_empty()).map(PathBuf::from));
        dirs.push(PathBuf::from("/var/lib/flatpak/exports/share"));
        dirs.extend(home.map(|h| h.join(".local/share/flatpak/exports/share")));
        dirs
    }

    /// `Name=` and `Icon=` of the desktop entry `id` (e.g. `code.desktop`).
    fn desktop_entry(id: &str) -> Option<(String, String)> {
        let text = data_dirs()
            .iter()
            .find_map(|dir| std::fs::read_to_string(dir.join("applications").join(id)).ok())?;
        let mut name = None;
        let mut icon = None;
        let mut in_entry = false;
        for line in text.lines() {
            let line = line.trim();
            if line.starts_with('[') {
                in_entry = line == "[Desktop Entry]";
                continue;
            }
            if !in_entry {
                continue;
            }
            if let Some(v) = line.strip_prefix("Name=") {
                name.get_or_insert_with(|| v.to_string());
            } else if let Some(v) = line.strip_prefix("Icon=") {
                icon.get_or_insert_with(|| v.to_string());
            }
        }
        Some((name?, icon.unwrap_or_default()))
    }

    /// A theme icon by name, as a file path (hicolor and pixmaps).
    fn icon_file(name: &str) -> Option<PathBuf> {
        if name.is_empty() {
            return None;
        }
        let as_path = PathBuf::from(name);
        if as_path.is_absolute() {
            return as_path.is_file().then_some(as_path);
        }
        const SIZES: &[&str] = &["64x64", "128x128", "256x256", "48x48", "512x512", "scalable"];
        for dir in data_dirs() {
            for size in SIZES {
                for ext in ["png", "svg"] {
                    let file = dir.join("icons/hicolor").join(size).join("apps").join(format!("{name}.{ext}"));
                    if file.is_file() {
                        return Some(file);
                    }
                }
            }
            for ext in ["png", "svg"] {
                let file = dir.join("pixmaps").join(format!("{name}.{ext}"));
                if file.is_file() {
                    return Some(file);
                }
            }
        }
        None
    }

    pub fn icon(path: &Path) -> Option<String> {
        let mime = match path.extension()?.to_str()? {
            "png" => "image/png",
            "svg" => "image/svg+xml",
            _ => return None,
        };
        let bytes = std::fs::read(path).ok()?;
        Some(format!("data:{mime};base64,{}", STANDARD.encode(bytes)))
    }

    /// Name and icon from the first desktop entry that exists, else `fallback`.
    fn describe(entries: &[&str], fallback: &str) -> (String, Option<PathBuf>) {
        entries
            .iter()
            .find_map(|id| desktop_entry(id))
            .map(|(name, icon)| (name, icon_file(&icon)))
            .unwrap_or_else(|| (fallback.to_string(), None))
    }

    pub fn find() -> Vec<Found> {
        let mut apps = Vec::new();

        // The folder's default handler, named after its desktop entry.
        let default = Command::new("xdg-mime")
            .args(["query", "default", "inode/directory"])
            .output()
            .ok()
            .map(|out| String::from_utf8_lossy(&out.stdout).trim().to_string())
            .filter(|id| !id.is_empty());
        let (name, icon_source) = match default.as_deref().and_then(desktop_entry) {
            Some((name, icon)) => (name, icon_file(&icon)),
            None => ("File manager".to_string(), icon_file("system-file-manager")),
        };
        apps.push(Found {
            id: "file-manager".into(),
            name,
            kind: AppKind::FileManager,
            icon_source,
            launch: Launch::new("xdg-open", &["{path}"]),
        });

        // (id, commands, desktop entries, fallback name, kind, args)
        let known: &[(&str, &[&str], &[&str], &str, AppKind, &[&str])] = &[
            ("vscode", &["code"], &["code.desktop", "com.visualstudio.code.desktop", "visual-studio-code.desktop"], "VS Code", AppKind::Editor, &["{path}"]),
            ("vscode-insiders", &["code-insiders"], &["code-insiders.desktop"], "VS Code Insiders", AppKind::Editor, &["{path}"]),
            ("cursor", &["cursor"], &["cursor.desktop"], "Cursor", AppKind::Editor, &["{path}"]),
            ("windsurf", &["windsurf"], &["windsurf.desktop"], "Windsurf", AppKind::Editor, &["{path}"]),
            ("zed", &["zed", "zeditor"], &["dev.zed.Zed.desktop", "zed.desktop"], "Zed", AppKind::Editor, &["{path}"]),
            ("sublime", &["subl"], &["sublime_text.desktop"], "Sublime Text", AppKind::Editor, &["{path}"]),
            ("gnome-terminal", &["gnome-terminal"], &["org.gnome.Terminal.desktop"], "Terminal", AppKind::Terminal, &["--working-directory={path}"]),
            ("ptyxis", &["ptyxis"], &["org.gnome.Ptyxis.desktop"], "Ptyxis", AppKind::Terminal, &["--new-window", "--working-directory={path}"]),
            ("konsole", &["konsole"], &["org.kde.konsole.desktop"], "Konsole", AppKind::Terminal, &["--workdir", "{path}"]),
            ("xfce4-terminal", &["xfce4-terminal"], &["xfce4-terminal.desktop"], "Xfce Terminal", AppKind::Terminal, &["--working-directory={path}"]),
            ("ghostty", &["ghostty"], &["com.mitchellh.ghostty.desktop"], "Ghostty", AppKind::Terminal, &["--working-directory={path}"]),
            ("kitty", &["kitty"], &["kitty.desktop"], "kitty", AppKind::Terminal, &["--directory", "{path}"]),
            ("alacritty", &["alacritty"], &["Alacritty.desktop"], "Alacritty", AppKind::Terminal, &["--working-directory", "{path}"]),
            ("wezterm", &["wezterm"], &["org.wezfurlong.wezterm.desktop"], "WezTerm", AppKind::Terminal, &["start", "--cwd", "{path}"]),
        ];
        for (id, commands, entries, fallback, kind, args) in known {
            let Some(program) = on_path(commands) else { continue };
            let (name, icon_source) = describe(entries, fallback);
            apps.push(Found {
                id: (*id).into(),
                name,
                kind: *kind,
                icon_source,
                launch: Launch::new(program, args).in_dir(),
            });
        }
        apps
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Lists what this machine has; `EVO_ICON_DUMP=<dir>` also writes the icons.
    #[test]
    fn detects_a_file_manager() {
        let apps = detect();
        for app in &apps {
            println!("{:<18} {:<22} icon: {}", app.id, app.name, app.icon.as_ref().map_or(0, |i| i.len()));
        }
        if let Some(dir) = std::env::var_os("EVO_ICON_DUMP") {
            use base64::{engine::general_purpose::STANDARD, Engine};
            for app in &apps {
                if let Some(data) = app.icon.as_ref().and_then(|i| i.strip_prefix("data:image/png;base64,")) {
                    std::fs::write(Path::new(&dir).join(format!("{}.png", app.id)), STANDARD.decode(data).unwrap()).unwrap();
                }
            }
        }
        assert_eq!(apps.first().map(|a| a.kind), Some(AppKind::FileManager));
    }
}
