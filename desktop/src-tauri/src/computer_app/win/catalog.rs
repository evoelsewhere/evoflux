//! The app catalog on Windows: every app with a window now, plus the
//! programs in the Start menu (see `computer_app::apps`).

use super::*;

/// A short app name from a window caption: "notes.txt - Notepad" gives
/// "Notepad", "Chat | Contoso | Microsoft Teams" gives "Microsoft Teams".
pub(super) fn caption_app_name(title: &str) -> Option<String> {
    let last = [" - ", " | ", " — "]
        .iter()
        .fold(title, |text, separator| text.rsplit(separator).next().unwrap_or(text))
        .trim();
    (!last.is_empty() && last.chars().count() <= 32).then(|| last.to_string())
}

pub(super) fn exe_stem(exe: &str) -> String {
    let stem = exe.strip_suffix(".exe").unwrap_or(exe);
    let mut chars = stem.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => String::new(),
    }
}

/// Target of a `.lnk` shortcut, when it points at a program.
fn shortcut_target(link: &std::path::Path) -> Option<String> {
    use windows::core::HSTRING;
    use windows::Win32::System::Com::{IPersistFile, STGM_READ};
    use windows::Win32::UI::Shell::{IShellLinkW, ShellLink};
    unsafe {
        let shell_link: IShellLinkW = CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER).ok()?;
        let file: IPersistFile = shell_link.cast().ok()?;
        file.Load(&HSTRING::from(link.as_os_str()), STGM_READ).ok()?;
        let mut buffer = [0u16; 1024];
        shell_link.GetPath(&mut buffer, std::ptr::null_mut(), 0).ok()?;
        let len = buffer.iter().position(|&unit| unit == 0).unwrap_or(buffer.len());
        let target = String::from_utf16_lossy(&buffer[..len]);
        target.to_lowercase().ends_with(".exe").then_some(target)
    }
}

fn start_menu_dirs() -> Vec<std::path::PathBuf> {
    ["ProgramData", "APPDATA"]
        .iter()
        .filter_map(|variable| std::env::var_os(variable))
        .map(|root| {
            std::path::PathBuf::from(root)
                .join("Microsoft")
                .join("Windows")
                .join("Start Menu")
                .join("Programs")
        })
        .filter(|dir| dir.is_dir())
        .collect()
}

static ICONS: Lazy<Mutex<HashMap<String, Option<String>>>> = Lazy::new(|| Mutex::new(HashMap::new()));

/// The program's own icon as a PNG data URL, cached per path.
pub(super) fn icon_data_url(path: &str) -> Option<String> {
    if let Some(cached) = ICONS.lock().ok()?.get(path) {
        return cached.clone();
    }
    // Icon extraction is a shell integration; a broken icon must not take
    // the whole list down with it.
    let icon = std::panic::catch_unwind(|| file_icon_provider::get_file_icon(path, 32))
        .ok()
        .and_then(Result::ok);
    let encoded = icon.and_then(|icon| {
        let image = RgbaImage::from_raw(icon.width, icon.height, icon.pixels)?;
        encode_png(&image).ok().map(|data| format!("data:image/png;base64,{data}"))
    });
    if let Ok(mut cache) = ICONS.lock() {
        cache.insert(path.to_string(), encoded.clone());
    }
    encoded
}

/// Everything with a window right now, plus the programs in the Start menu.
pub(super) fn app_catalog() -> Catalog {
    let own = unsafe { GetCurrentProcessId() };
    let mut apps = Catalog::new();
    for row in top_level_windows().into_iter().filter_map(describe_window) {
        // A Store app whose frame does not say which app it is (see
        // `app_name`) cannot be allowed or blocked by name.
        if row.pid == own || is_protected_process_name(&row.app) || row.app.eq_ignore_ascii_case(FRAME_HOST) {
            continue;
        }
        let Some(path) = process_image_path(app_process(row.hwnd, row.pid)) else {
            continue;
        };
        let exe = file_name(&path).to_lowercase();
        let name = caption_app_name(&row.title).unwrap_or_else(|| exe_stem(&exe));
        apps.entry(exe)
            .and_modify(|entry| entry.running = true)
            .or_insert(AppEntry { name, launch: path.clone(), path, running: true });
    }
    let links: Vec<(String, std::path::PathBuf)> = start_menu_dirs()
        .into_iter()
        .flat_map(|dir| walkdir::WalkDir::new(dir).max_depth(4).into_iter().filter_map(Result::ok))
        .filter(|entry| {
            entry.path().extension().and_then(|ext| ext.to_str()).map(str::to_lowercase)
                == Some("lnk".to_string())
        })
        .filter_map(|entry| {
            let name = entry.path().file_stem()?.to_str()?.to_string();
            let lower = name.to_lowercase();
            let noise = ["uninstall", "readme", "help", "website", "documentation"];
            (!name.is_empty() && !noise.iter().any(|word| lower.contains(word)))
                .then(|| (name, entry.path().to_path_buf()))
        })
        .collect();
    let resolved = in_parallel(links, |(name, link)| {
        shortcut_target(&link).map(|path| (name, path, link))
    });
    for (name, path, link) in resolved.into_iter().flatten() {
        let exe = file_name(&path).to_lowercase();
        if is_protected_process_name(&exe) {
            continue;
        }
        let launch = link.to_string_lossy().into_owned();
        // The Start menu's name for a program beats one read off a caption,
        // and its shortcut is how the program is meant to be started.
        apps.entry(exe)
            .and_modify(|entry| {
                entry.name = name.clone();
                entry.launch = launch.clone();
            })
            .or_insert(AppEntry { name, path, launch, running: false });
    }
    apps
}

/// Apps a user might allow or block, each with its icon. Keyed by
/// executable name, which is what the policy matches on.
pub(super) fn list_apps() -> Value {
    // Icons one at a time: the shell's icon extraction is not reliable when
    // several threads ask at once (measured: some icons came back empty).
    let apps: Vec<Value> = sorted(app_catalog())
        .into_iter()
        .map(|(exe, entry)| {
            json!({
                "exe": exe,
                "name": entry.name,
                "running": entry.running,
                "icon": icon_data_url(&entry.path),
            })
        })
        .collect();
    json!({ "apps": apps })
}

/// Map `items` with `work` on a few COM-initialised threads, keeping order.
/// Resolving a shortcut takes tens of milliseconds, which adds up to seconds
/// for a full Start menu.
fn in_parallel<T: Send, R: Send>(items: Vec<T>, work: impl Fn(T) -> R + Sync) -> Vec<R> {
    const THREADS: usize = 8;
    let chunk = items.len().div_ceil(THREADS).max(1);
    let mut chunks: Vec<Vec<T>> = Vec::new();
    let mut items = items.into_iter().peekable();
    while items.peek().is_some() {
        chunks.push(items.by_ref().take(chunk).collect());
    }
    std::thread::scope(|scope| {
        let handles: Vec<_> = chunks
            .into_iter()
            .map(|chunk| {
                let work = &work;
                scope.spawn(move || {
                    unsafe {
                        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
                    }
                    chunk.into_iter().map(work).collect::<Vec<R>>()
                })
            })
            .collect();
        handles
            .into_iter()
            .flat_map(|handle| handle.join().unwrap_or_default())
            .collect()
    })
}
