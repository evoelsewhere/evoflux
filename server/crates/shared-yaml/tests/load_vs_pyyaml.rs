//! `load` against PyYAML 6 `safe_load` on the corpus in `fixtures/gen_fixtures.py`.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

mod common;

use evoflux_shared_yaml::{load, Value, YamlError};

const CASES: &str = include_str!("fixtures/load_cases.json");

#[test]
fn every_document_loads_like_pyyaml() {
    let cases: Vec<serde_json::Value> = serde_json::from_str(CASES).unwrap();
    assert!(cases.len() >= 60, "corpus shrank to {}", cases.len());
    let mut failures = Vec::new();
    for case in &cases {
        let text = case["yaml"].as_str().unwrap();
        let got = load(text);
        match (case.get("value"), got) {
            (Some(want), Ok(got)) => {
                let want = common::decode(want);
                if !common::same(&want, &got) {
                    failures.push(format!("{text:?}\n  want {want:?}\n  got  {got:?}"));
                }
            }
            (None, Err(_)) => {}
            (Some(_), Err(e)) => failures.push(format!("{text:?}\n  unexpected error {e}")),
            (None, Ok(got)) => failures.push(format!(
                "{text:?}\n  PyYAML raised {}, got {got:?}",
                case["error"]
            )),
        }
    }
    assert!(
        failures.is_empty(),
        "{} of {} cases differ:\n{}",
        failures.len(),
        cases.len(),
        failures.join("\n")
    );
}

#[test]
fn a_yaml_1_1_scalar_name_is_not_a_name() {
    let meta = load("name: off\n").unwrap();
    assert_eq!(meta.get("name"), Some(&Value::Bool(false)));
}

#[test]
fn billion_laughs_is_refused() {
    let mut doc = String::from("a0: &a0 [x, x, x, x, x, x, x, x, x, x]\n");
    for i in 1..10 {
        let p = i - 1;
        doc.push_str(&format!(
            "a{i}: &a{i} [*a{p}, *a{p}, *a{p}, *a{p}, *a{p}, *a{p}, *a{p}, *a{p}, *a{p}, *a{p}]\n"
        ));
    }
    assert!(matches!(load(&doc), Err(YamlError::TooLarge(_))));
}

#[test]
fn deep_flow_nesting_is_an_error_not_a_crash() {
    let doc = format!("{}{}", "[".repeat(5_000), "]".repeat(5_000));
    assert!(load(&doc).is_err());
}

#[test]
fn deep_block_nesting_is_an_error_not_a_crash() {
    let doc: String = (0..3_000)
        .map(|i| format!("{}k:\n", " ".repeat(i)))
        .collect();
    assert!(load(&doc).is_err());
}

#[test]
fn errors_do_not_echo_the_document() {
    for text in [
        "a: !!int s3cr3t-value\n",
        "a: !!bool s3cr3t-value\n",
        "a: [s3cr3t-value\n",
    ] {
        let error = load(text).unwrap_err().to_string();
        assert!(!error.contains("s3cr3t"), "{error}");
    }
}

#[test]
fn garbage_never_panics() {
    let alphabet = [
        "a", ":", " ", "\n", "-", "[", "]", "{", "}", "&x", "*x", "!!", "'", "\"", "|", ">", "#",
        "<<", "?", ",", "\t", "1", "é", "%",
    ];
    let mut seed: u64 = 0x9e37_79b9_7f4a_7c15;
    for _ in 0..5_000 {
        let mut doc = String::new();
        for _ in 0..24 {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            doc.push_str(alphabet[(seed % alphabet.len() as u64) as usize]);
        }
        let _ = load(&doc);
    }
}
