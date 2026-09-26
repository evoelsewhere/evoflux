//! The app catalog on macOS: every app with a window now, plus the `.app`
//! bundles in the Applications folders (see `computer_app::apps`).

use super::*;

static ICONS: Lazy<Mutex<HashMap<String, Option<String>>>> = Lazy::new(|| Mutex::new(HashMap::new()));

/// The app's own icon as a PNG data URL, cached per path.
fn icon_data_url(path: &str) -> Option<String> {
    if let Some(cached) = ICONS.lock().ok()?.get(path) {
        return cached.clone();
    }
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

/// The executable inside an `.app` bundle: `Contents/MacOS/<name>`, the one
/// named like the bundle when there are several.
fn bundle_executable(bundle: &std::path::Path) -> Option<String> {
    let stem = bundle.file_stem()?.to_str()?.to_string();
    let entries: Vec<String> = std::fs::read_dir(bundle.join("Contents").join("MacOS"))
        .ok()?
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().map(|kind| kind.is_file()).unwrap_or(false))
        .filter_map(|entry| entry.file_name().to_str().map(str::to_string))
        .collect();
    entries
        .iter()
        .find(|name| name.eq_ignore_ascii_case(&stem))
        .or_else(|| entries.first())
        .cloned()
}

fn application_dirs() -> Vec<std::path::PathBuf> {
    let mut dirs = vec![
        std::path::PathBuf::from("/Applications"),
        std::path::PathBuf::from("/System/Applications"),
    ];
    if let Some(home) = std::env::var_os("HOME") {
        dirs.push(std::path::PathBuf::from(home).join("Applications"));
    }
    dirs.into_iter().filter(|dir| dir.is_dir()).collect()
}

/// Everything with a window right now, plus the installed applications.
/// An app is opened through its `.app` bundle; one running from a bare
/// executable has no `launch` and cannot be opened.
pub(super) fn app_catalog() -> Catalog {
    let mut apps = Catalog::new();
    for row in window_rows() {
        if attach_refusal(&row).is_some() {
            continue;
        }
        let Some(path) = process_path(row.pid) else {
            continue;
        };
        let bundle = bundle_of(&path);
        let name = bundle
            .as_ref()
            .and_then(|bundle| bundle.file_stem()?.to_str().map(str::to_string))
            .unwrap_or_else(|| row.app.clone());
        let launch = bundle
            .map(|bundle| bundle.to_string_lossy().into_owned())
            .unwrap_or_default();
        let path = if launch.is_empty() { path } else { launch.clone() };
        apps.entry(row.app.to_lowercase())
            .and_modify(|entry| entry.running = true)
            .or_insert(AppEntry { name, path, launch, running: true });
    }
    for dir in application_dirs() {
        let bundles = walkdir::WalkDir::new(&dir)
            .max_depth(2)
            .into_iter()
            .filter_map(Result::ok)
            .filter(|entry| entry.path().extension().and_then(|ext| ext.to_str()) == Some("app"));
        for entry in bundles {
            let bundle = entry.path();
            // Skip helper apps nested inside other bundles.
            if bundle.parent().is_some_and(|parent| parent.to_string_lossy().contains(".app")) {
                continue;
            }
            let (Some(executable), Some(name)) = (
                bundle_executable(bundle),
                bundle.file_stem().and_then(|stem| stem.to_str()).map(str::to_string),
            ) else {
                continue;
            };
            if is_protected_process_name(&executable) {
                continue;
            }
            let bundle = bundle.to_string_lossy().into_owned();
            apps.entry(executable.to_lowercase())
                .and_modify(|entry| {
                    entry.name = name.clone();
                    if entry.launch.is_empty() {
                        entry.launch = bundle.clone();
                    }
                })
                .or_insert(AppEntry {
                    name,
                    path: bundle.clone(),
                    launch: bundle,
                    running: false,
                });
        }
    }
    apps
}

/// Apps a user might allow or block, each with its icon. Keyed by
/// executable name, which is what the policy matches on.
pub(super) fn list_apps() -> Value {
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
