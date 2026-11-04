#![allow(clippy::unwrap_used)]

use std::collections::HashMap;
use std::path::PathBuf;

use evoflux_area_chat_core::workspace::{self, Allowed};
use evoflux_core::config::Settings;

#[test]
fn workspace_policy_is_available_to_other_crates() {
    let temp = tempfile::tempdir().unwrap();
    let home = temp.path().join("home");
    let root = home.join("projects");
    let config = temp.path().join("config");
    let vars = HashMap::from([(
        "EVOFLUX_WORKSPACE_DIR".to_owned(),
        root.to_string_lossy().into_owned(),
    )]);
    let settings = Settings::from_vars(&vars, Some(&home), &config).unwrap();
    let allowed = Allowed::current(&settings);
    let path = workspace::resolve(&root.join("project").to_string_lossy(), &home).unwrap();
    assert_eq!(allowed.refusal(&path), None);
    assert!(allowed.refusal(&home).is_some());
    assert_eq!(workspace::strip_verbatim(path.clone()), path);
    assert!(workspace::resolve("relative", &home).is_none());
    assert!(workspace::ALLOW_HINT.contains("EVOFLUX_WORKSPACE_ROOTS"));
    assert_eq!(
        workspace::strip_verbatim(PathBuf::from("relative")),
        PathBuf::from("relative")
    );
}
