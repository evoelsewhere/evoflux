#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use evoflux_gateway::routing::{
    parse_rust_ready, rust_forward_enabled, Owner, RoutingError, RoutingTable,
};
use std::path::PathBuf;

const SAMPLE: &str = r#"
[[unit]]
name = "health"
owner = "python"
routes = ["/api/health/**"]
services = []

[[unit]]
name = "health-live"
owner = "rust"
routes = ["/api/health/live/**"]
services = ["otel_retention"]

[[unit]]
name = "scheduler"
owner = "python"
routes = ["/api/scheduler/**", "/metrics"]
services = ["scheduler", "dream_scheduler"]

[[unit]]
name = "team"
owner = "python"
routes = ["/api/team/**"]
services = []

[[unit]]
name = "terminal"
owner = "rust"
routes = ["/api/team/{session_id}/terminal/**", "/api/team/{session_id}/terminals"]
services = []

[[unit]]
name = "web"
owner = "python"
routes = ["/**"]
services = []
"#;

#[allow(clippy::disallowed_methods)] // sync test, no async runtime involved
fn write(contents: &str) -> (tempfile::TempDir, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("routing.toml");
    std::fs::write(&path, contents).unwrap();
    (dir, path)
}

fn load(override_env: Option<&str>) -> Result<RoutingTable, RoutingError> {
    let (_dir, path) = write(SAMPLE);
    RoutingTable::load(&path, override_env)
}

#[test]
fn longest_prefix_wins() {
    let table = load(None).unwrap();
    assert_eq!(table.owner_for("/api/health/live"), Owner::Rust);
    assert_eq!(table.owner_for("/api/health/live/deep"), Owner::Rust);
    assert_eq!(table.owner_for("/api/health"), Owner::Python);
    assert_eq!(table.owner_for("/api/health/ready"), Owner::Python);
    assert_eq!(
        table.unit_for("/api/health/live").unwrap().name,
        "health-live"
    );
    assert_eq!(table.unit_for("/api/health/ready").unwrap().name, "health");
}

#[test]
fn prefix_matches_on_segment_boundaries_only() {
    let table = load(None).unwrap();
    // `/api/health/livez` is not under `/api/health/live/**`.
    assert_eq!(table.unit_for("/api/health/livez").unwrap().name, "health");
    assert_eq!(table.unit_for("/api/healthz").unwrap().name, "web");
}

#[test]
fn exact_route_matches_only_that_path() {
    let table = load(None).unwrap();
    assert_eq!(table.unit_for("/metrics").unwrap().name, "scheduler");
    assert_eq!(table.unit_for("/metrics/gateway").unwrap().name, "web");
}

#[test]
fn empty_base_catch_all_covers_root_and_spa_paths() {
    let table = load(None).unwrap();
    assert_eq!(table.unit_for("/").unwrap().name, "web");
    assert_eq!(table.unit_for("/assets/index.js").unwrap().name, "web");
}

#[test]
fn param_route_beats_broader_rest_route() {
    let table = load(None).unwrap();
    for path in [
        "/api/team/abc123/terminal",
        "/api/team/abc123/terminal/x",
        "/api/team/abc123/terminals",
    ] {
        assert_eq!(table.unit_for(path).unwrap().name, "terminal", "{path}");
        assert_eq!(table.owner_for(path), Owner::Rust, "{path}");
    }
    assert_eq!(table.unit_for("/api/team/abc123").unwrap().name, "team");
    assert_eq!(
        table.unit_for("/api/team/abc123/messages").unwrap().name,
        "team"
    );
}

#[test]
fn param_matches_exactly_one_non_empty_segment() {
    let table = load(None).unwrap();
    // Two segments where `{session_id}` stands for one.
    assert_eq!(
        table.unit_for("/api/team/a/b/terminal/x").unwrap().name,
        "team"
    );
    // An empty segment is not a parameter value.
    assert_eq!(table.unit_for("/api/team//terminal").unwrap().name, "team");
    // A decoded `/` splits the segment, as Starlette routes it.
    assert_eq!(
        table.unit_for("/api/team/a%2Fb/terminal").unwrap().name,
        "team"
    );
}

#[test]
fn literal_beats_param() {
    let toml = r#"
[[unit]]
name = "param"
owner = "rust"
routes = ["/api/team/{session_id}/**"]
services = []

[[unit]]
name = "literal"
owner = "python"
routes = ["/api/team/new/**"]
services = []
"#;
    let (_dir, path) = write(toml);
    let table = RoutingTable::load(&path, None).unwrap();
    assert_eq!(table.unit_for("/api/team/new/x").unwrap().name, "literal");
    assert_eq!(table.unit_for("/api/team/other/x").unwrap().name, "param");
}

#[test]
fn routes_differing_only_in_param_names_are_duplicates() {
    let toml = r#"
[[unit]]
name = "a"
owner = "python"
routes = ["/api/x/{id}"]
services = []

[[unit]]
name = "b"
owner = "rust"
routes = ["/api/x/{other}"]
services = []
"#;
    let (_dir, path) = write(toml);
    assert!(matches!(
        RoutingTable::load(&path, None),
        Err(RoutingError::DuplicateRoute { .. })
    ));
}

#[test]
fn malformed_patterns_are_errors() {
    for route in [
        "/api/x/",
        "/api//x",
        "/api/x**",
        "/api/**/x",
        "/api/*",
        "/api/{}",
        "/api/{id",
        "/api/id}",
        "/api/pre{id}",
    ] {
        let toml = format!(
            "[[unit]]\nname = \"a\"\nowner = \"python\"\nroutes = [\"{route}\"]\nservices = []\n"
        );
        let (_dir, path) = write(&toml);
        assert!(
            matches!(
                RoutingTable::load(&path, None),
                Err(RoutingError::InvalidRoute { .. })
            ),
            "{route} should be rejected"
        );
    }
}

#[test]
fn unmatched_goes_to_python() {
    let toml = r#"
[[unit]]
name = "health-live"
owner = "rust"
routes = ["/api/health/live/**"]
services = []
"#;
    let (_dir, path) = write(toml);
    let table = RoutingTable::load(&path, None).unwrap();
    assert_eq!(table.owner_for("/api/agents"), Owner::Python);
    assert!(table.unit_for("/api/agents").is_none());
    assert_eq!(table.owner_for("/api/health/live"), Owner::Rust);
}

#[test]
fn percent_encoded_paths_route_like_starlette() {
    let table = load(None).unwrap();
    // Starlette routes on the decoded path, so the gateway must too.
    assert_eq!(table.owner_for("/api/health/%6Cive"), Owner::Rust);
}

#[test]
fn override_env_flips_a_unit() {
    let table = load(Some("health-live=python, scheduler=rust")).unwrap();
    assert_eq!(table.owner_for("/api/health/live"), Owner::Python);
    assert_eq!(table.owner_for("/api/scheduler/tasks"), Owner::Rust);
    assert_eq!(table.owner_for("/metrics"), Owner::Rust);
}

#[test]
fn empty_override_changes_nothing() {
    let table = load(Some("  ")).unwrap();
    assert_eq!(table.owner_for("/api/health/live"), Owner::Rust);
}

#[test]
fn unknown_unit_in_override_is_an_error() {
    match load(Some("health-live=python,nope=rust")) {
        Err(RoutingError::UnknownOverrideUnit(name)) => assert_eq!(name, "nope"),
        other => panic!("expected UnknownOverrideUnit, got {other:?}"),
    }
}

#[test]
fn malformed_override_is_an_error() {
    assert!(matches!(
        load(Some("health-live")),
        Err(RoutingError::InvalidOverride(_))
    ));
    assert!(matches!(
        load(Some("health-live=go")),
        Err(RoutingError::InvalidOverride(_))
    ));
}

#[test]
fn disabled_python_services_lists_only_rust_units() {
    let table = load(None).unwrap();
    assert_eq!(table.disabled_python_services(), vec!["otel_retention"]);
    let flipped = load(Some("scheduler=rust,health-live=python")).unwrap();
    assert_eq!(
        flipped.disabled_python_services(),
        vec!["scheduler", "dream_scheduler"]
    );
}

#[test]
fn shadow_units_keep_their_services_in_python() {
    let table = load(Some("scheduler=shadow")).unwrap();
    assert_eq!(table.owner_for("/api/scheduler/tasks"), Owner::Shadow);
    assert_eq!(table.disabled_python_services(), vec!["otel_retention"]);
}

#[test]
fn duplicate_route_across_units_is_an_error() {
    let toml = r#"
[[unit]]
name = "a"
owner = "python"
routes = ["/api/x/**"]
services = []

[[unit]]
name = "b"
owner = "rust"
routes = ["/api/x/**"]
services = []
"#;
    let (_dir, path) = write(toml);
    assert!(matches!(
        RoutingTable::load(&path, None),
        Err(RoutingError::DuplicateRoute { .. })
    ));
}

#[test]
fn invalid_route_and_owner_are_errors() {
    let bad_route = r#"
[[unit]]
name = "a"
owner = "python"
routes = ["api/x"]
services = []
"#;
    let (_dir, path) = write(bad_route);
    assert!(matches!(
        RoutingTable::load(&path, None),
        Err(RoutingError::InvalidRoute { .. })
    ));
    let bad_owner = r#"
[[unit]]
name = "a"
owner = "go"
routes = ["/api/x"]
services = []
"#;
    let (_dir, path) = write(bad_owner);
    assert!(matches!(
        RoutingTable::load(&path, None),
        Err(RoutingError::Parse(_))
    ));
}

#[test]
fn repository_routing_toml_loads() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../routing.toml");
    let table = RoutingTable::load(&path, None).unwrap();
    assert_eq!(table.owner_for("/api/health/live"), Owner::Python);
    assert_eq!(
        table.unit_for("/api/health/live").unwrap().name,
        "edge-stateless"
    );
    assert_eq!(
        table.unit_for("/api/health/ready").unwrap().name,
        "health-diagnostics"
    );
    assert_eq!(table.unit_for("/").unwrap().name, "platform-meta");
    assert!(table.disabled_python_services().is_empty());
}

fn repository_table() -> RoutingTable {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../routing.toml");
    RoutingTable::load(&path, None).unwrap()
}

/// The cases spelled out in the `routing.toml` header and by `check_board.py`.
#[test]
fn repository_table_follows_the_matching_contract() {
    let table = repository_table();
    for (path, unit) in [
        ("/api/team/abc/terminal/x", "terminal-processes"),
        ("/api/team/workspace/files/read", "workspace-files"),
        ("/api/team/abc/files/watch", "terminal-processes"),
        ("/api/team/abc/files/read", "workspace-files"),
    ] {
        assert_eq!(table.unit_for(path).unwrap().name, unit, "{path}");
    }
    // The web UI catch-all never serves an /api path the table knows about.
    assert_ne!(table.unit_for("/api/team/x").unwrap().name, "platform-meta");
}

#[test]
fn segment_count_outranks_literal_count() {
    let toml = r#"
[[unit]]
name = "short"
owner = "python"
routes = ["/api/team/workspace/**"]
services = []

[[unit]]
name = "long"
owner = "rust"
routes = ["/api/team/{session_id}/files/**"]
services = []
"#;
    let table = RoutingTable::from_toml(toml, None).unwrap();
    // 5 segments (3 literals) beat 4 segments (4 literals).
    assert_eq!(
        table.unit_for("/api/team/workspace/files/x").unwrap().name,
        "long"
    );
    assert_eq!(
        table.unit_for("/api/team/workspace/other").unwrap().name,
        "short"
    );
}

#[test]
fn exact_beats_glob_with_the_same_segments() {
    let toml = r#"
[[unit]]
name = "glob"
owner = "python"
routes = ["/api/x/**"]
services = []

[[unit]]
name = "exact"
owner = "rust"
routes = ["/api/x"]
services = []
"#;
    let table = RoutingTable::from_toml(toml, None).unwrap();
    assert_eq!(table.unit_for("/api/x").unwrap().name, "exact");
    assert_eq!(table.unit_for("/api/x/y").unwrap().name, "glob");
}

#[test]
fn path_param_takes_the_rest_of_the_path() {
    let toml = r#"
[[unit]]
name = "files"
owner = "rust"
routes = ["/api/files/{file_path:path}"]
services = []

[[unit]]
name = "web"
owner = "python"
routes = ["/**"]
services = []
"#;
    let table = RoutingTable::from_toml(toml, None).unwrap();
    assert_eq!(table.unit_for("/api/files/a").unwrap().name, "files");
    assert_eq!(table.unit_for("/api/files/a/b/c").unwrap().name, "files");
    assert_eq!(table.unit_for("/api/files/").unwrap().name, "web");
    assert_eq!(table.unit_for("/api/files").unwrap().name, "web");
    assert!(RoutingTable::from_toml(
        "[[unit]]\nname = \"a\"\nowner = \"python\"\nroutes = [\"/a/{p:path}/b\"]\n",
        None
    )
    .is_err());
}

#[test]
fn ties_go_to_the_first_route_in_the_table() {
    let toml = r#"
[[unit]]
name = "first"
owner = "python"
routes = ["/api/{a}/b"]
services = []

[[unit]]
name = "second"
owner = "rust"
routes = ["/api/a/{b}"]
services = []
"#;
    let table = RoutingTable::from_toml(toml, None).unwrap();
    assert_eq!(table.unit_for("/api/a/b").unwrap().name, "first");
}

#[test]
fn pin_breakers_are_accepted() {
    let toml = r#"
[[unit]]
name = "a"
owner = "python"
pin_breakers = ["file-lock"]
routes = ["/api/a/**"]
services = []
"#;
    let table = RoutingTable::from_toml(toml, None).unwrap();
    assert_eq!(table.units()[0].pin_breakers, vec!["file-lock"]);
}

fn forward(ready: &[&str], override_env: Option<&str>) -> Result<RoutingTable, RoutingError> {
    let ready: Vec<String> = ready.iter().map(|s| (*s).to_owned()).collect();
    RoutingTable::from_toml_forward(SAMPLE, override_env, &ready)
}

#[test]
fn rust_forward_with_an_empty_list_is_a_no_op() {
    let table = forward(&[], None).unwrap();
    assert_eq!(table.owner_for("/api/scheduler/tasks"), Owner::Python);
    assert_eq!(table.owner_for("/api/health/live"), Owner::Rust);
    assert!(table.forwarded_units().is_empty());
}

#[test]
fn rust_forward_flips_a_listed_unit_to_rust() {
    let table = forward(&["scheduler"], None).unwrap();
    assert_eq!(table.owner_for("/api/scheduler/tasks"), Owner::Rust);
    assert_eq!(table.owner_for("/metrics"), Owner::Rust);
    assert_eq!(table.owner_for("/api/team/x"), Owner::Python);
    assert_eq!(table.forwarded_units(), ["scheduler"]);
}

#[test]
fn explicit_override_beats_rust_forward() {
    let table = forward(&["scheduler", "team"], Some("scheduler=python")).unwrap();
    assert_eq!(table.owner_for("/api/scheduler/tasks"), Owner::Python);
    assert_eq!(table.owner_for("/api/team/x"), Owner::Rust);
    assert_eq!(table.forwarded_units(), ["team"]);
}

#[test]
fn explicit_shadow_override_beats_rust_forward() {
    let table = forward(&["team"], Some("team=shadow")).unwrap();
    assert_eq!(table.owner_for("/api/team/x"), Owner::Shadow);
}

#[test]
fn unit_already_on_rust_is_not_reported_as_forwarded() {
    let table = forward(&["health-live", "team"], None).unwrap();
    assert_eq!(table.forwarded_units(), ["team"]);
}

#[test]
fn unknown_rust_ready_unit_is_an_error() {
    match forward(&["scheduler", "nope"], None) {
        Err(RoutingError::UnknownRustReadyUnit(name)) => assert_eq!(name, "nope"),
        other => panic!("expected UnknownRustReadyUnit, got {other:?}"),
    }
}

#[test]
fn rust_ready_file_lists_units() {
    assert!(parse_rust_ready("units = []").unwrap().is_empty());
    assert_eq!(
        parse_rust_ready(
            "# note
units = [\"a\", \"b\"]"
        )
        .unwrap(),
        ["a", "b"]
    );
    assert!(matches!(
        parse_rust_ready("units = 3"),
        Err(RoutingError::Parse(_))
    ));
    assert!(matches!(
        parse_rust_ready("unit = []"),
        Err(RoutingError::Parse(_))
    ));
}

#[test]
fn rust_forward_env_values() {
    for on in ["1", "true", "on", "TRUE", "On", " 1 "] {
        assert!(rust_forward_enabled(Some(on)), "{on:?}");
    }
    for off in ["", "0", "false", "off", "yes", "2", "enabled"] {
        assert!(!rust_forward_enabled(Some(off)), "{off:?}");
    }
    assert!(!rust_forward_enabled(None));
}

#[test]
fn repository_rust_ready_units_exist_in_routing_toml() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    #[allow(clippy::disallowed_methods)] // sync test, no async runtime involved
    let ready =
        parse_rust_ready(&std::fs::read_to_string(root.join("rust-ready.toml")).unwrap()).unwrap();
    #[allow(clippy::disallowed_methods)]
    let text = std::fs::read_to_string(root.join("routing.toml")).unwrap();
    RoutingTable::from_toml_forward(&text, None, &ready).unwrap();
}
