//! The app catalog: every app with a window now, plus the installed ones.
//!
//! Each backend builds it its own way (running windows and Start menu
//! shortcuts on Windows, running windows and `.app` bundles on macOS). The
//! Settings picker lists it with icons; the agent searches it with
//! `search_apps` and launches from it with `open_app`, so only an app the
//! catalog knows can be opened — never an arbitrary path or command line.

use std::collections::HashMap;

use serde_json::{json, Value};

pub(crate) struct AppEntry {
    pub name: String,
    /// The program itself, where its icon comes from.
    pub path: String,
    /// What opening the app runs: a Start menu shortcut (which keeps its
    /// arguments and working folder), an `.app` bundle, or the program.
    pub launch: String,
    pub running: bool,
}

/// Apps keyed by executable name, lowercased — what the allow and block
/// lists match on.
pub(crate) type Catalog = HashMap<String, AppEntry>;

/// `Notepad.EXE` → `notepad`, `TextEdit` → `textedit`.
fn normalize(exe: &str) -> String {
    let lower = exe.trim().to_lowercase();
    lower.strip_suffix(".exe").map(str::to_string).unwrap_or(lower)
}

/// Running apps first, then by name.
pub(crate) fn sorted(catalog: Catalog) -> Vec<(String, AppEntry)> {
    let mut list: Vec<(String, AppEntry)> = catalog.into_iter().collect();
    list.sort_by(|(_, a), (_, b)| {
        b.running.cmp(&a.running).then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });
    list
}

/// How well `query` names the app, best first; `None` when it does not.
fn rank(exe: &str, entry: &AppEntry, query: &str) -> Option<u8> {
    let exe = normalize(exe);
    let name = entry.name.to_lowercase();
    if exe == query || name == query {
        Some(0)
    } else if exe.starts_with(query) || name.starts_with(query) {
        Some(1)
    } else if name.split_whitespace().any(|word| word.starts_with(query)) {
        Some(2)
    } else if exe.contains(query) || name.contains(query) {
        Some(3)
    } else {
        None
    }
}

/// The `search_apps` result: apps matching `query` (all of them without
/// one), best match first, at most `limit`.
pub(crate) fn search(catalog: Catalog, query: Option<&str>, limit: usize) -> Value {
    let query = query.map(normalize).filter(|query| !query.is_empty());
    let mut matches: Vec<(u8, String, AppEntry)> = sorted(catalog)
        .into_iter()
        .filter_map(|(exe, entry)| {
            let rank = match &query {
                Some(query) => rank(&exe, &entry, query)?,
                None => 0,
            };
            Some((rank, exe, entry))
        })
        .collect();
    // Stable, so running apps stay ahead within a rank.
    matches.sort_by_key(|(rank, _, _)| *rank);
    let total = matches.len();
    let apps: Vec<Value> = matches
        .into_iter()
        .take(limit)
        .map(|(_, exe, entry)| json!({ "exe": exe, "name": entry.name, "running": entry.running }))
        .collect();
    json!({ "count": apps.len(), "total": total, "apps": apps })
}

/// The catalog entry for `exe` exactly, as `search_apps` reported it.
pub(crate) fn find<'a>(catalog: &'a Catalog, exe: &str) -> Result<(&'a str, &'a AppEntry), String> {
    let wanted = normalize(exe);
    catalog
        .iter()
        .find(|(key, _)| normalize(key) == wanted)
        .map(|(key, entry)| (key.as_str(), entry))
        .ok_or_else(|| format!("{exe} is not an installed or running app. Call search_apps and pass the exe it lists."))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn catalog() -> Catalog {
        let entry = |name: &str, running: bool| AppEntry {
            name: name.into(),
            path: String::new(),
            launch: String::new(),
            running,
        };
        HashMap::from([
            ("notepad.exe".to_string(), entry("Notepad", false)),
            ("notepad++.exe".to_string(), entry("Notepad++", true)),
            ("ms-teams.exe".to_string(), entry("Microsoft Teams", false)),
            ("excel.exe".to_string(), entry("Excel", true)),
        ])
    }

    fn exes(result: &Value) -> Vec<&str> {
        result["apps"].as_array().unwrap().iter().map(|app| app["exe"].as_str().unwrap()).collect()
    }

    #[test]
    fn ranks_exact_names_before_partial_ones() {
        let result = search(catalog(), Some("Notepad"), 10);
        assert_eq!(exes(&result), ["notepad.exe", "notepad++.exe"]);
        assert_eq!(exes(&search(catalog(), Some("teams"), 10)), ["ms-teams.exe"]);
        assert_eq!(exes(&search(catalog(), Some("excel.exe"), 10)), ["excel.exe"]);
        assert_eq!(search(catalog(), Some("photoshop"), 10)["count"], 0);
    }

    #[test]
    fn lists_running_apps_first_without_a_query_and_honours_the_limit() {
        let result = search(catalog(), None, 2);
        assert_eq!(result["total"], 4);
        assert_eq!(exes(&result), ["excel.exe", "notepad++.exe"]);
    }

    #[test]
    fn finds_only_an_exact_executable() {
        let catalog = catalog();
        assert_eq!(find(&catalog, "NOTEPAD").unwrap().0, "notepad.exe");
        assert_eq!(find(&catalog, "notepad.exe").unwrap().0, "notepad.exe");
        assert!(find(&catalog, "note").is_err());
        assert!(find(&catalog, "C:\\Windows\\notepad.exe").is_err());
    }
}
