//! `spec()` must equal what Python sends the model for each tool.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]

use evoflux_area_tools::read_only_tools;
use serde_json::Value;

fn snapshot() -> Value {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/snapshots/specs.json");
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

#[test]
fn every_spec_equals_the_python_definition() {
    let expected = snapshot();
    let tools = read_only_tools();
    assert_eq!(
        tools.len(),
        expected.as_object().unwrap().len(),
        "tool set differs from the snapshot"
    );
    for tool in tools {
        assert_eq!(
            tool.spec(),
            expected[tool.name()],
            "spec for {} differs from Python",
            tool.name()
        );
    }
}

#[test]
fn spec_text_is_byte_identical_including_key_order_within_properties() {
    // Equality above ignores key order; the model sees the serialised text,
    // so compare the serialised property keys too.
    let expected = snapshot();
    for tool in read_only_tools() {
        let ours = tool.spec();
        let theirs = &expected[tool.name()];
        let keys = |v: &Value| -> Vec<String> {
            v["function"]["parameters"]["properties"]
                .as_object()
                .unwrap()
                .keys()
                .cloned()
                .collect()
        };
        assert_eq!(
            keys(&ours),
            keys(theirs),
            "property order for {}",
            tool.name()
        );
    }
}
