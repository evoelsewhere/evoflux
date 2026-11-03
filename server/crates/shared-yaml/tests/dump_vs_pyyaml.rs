//! `dump` against PyYAML 6 `safe_dump` on the values in `fixtures/gen_fixtures.py`,
//! for every combination of `sort_keys` and `allow_unicode`.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

mod common;

use evoflux_shared_yaml::{dump, load, DumpOpts, Value};

const CASES: &str = include_str!("fixtures/dump_cases.json");
const LOAD_CASES: &str = include_str!("fixtures/load_cases.json");

#[test]
fn every_value_dumps_like_pyyaml() {
    let cases: Vec<serde_json::Value> = serde_json::from_str(CASES).unwrap();
    assert!(cases.len() >= 60, "corpus shrank to {}", cases.len());
    let mut failures = Vec::new();
    let mut checked = 0;
    for case in &cases {
        let value = common::decode(&case["value"]);
        for sort_keys in [false, true] {
            for allow_unicode in [false, true] {
                let name = format!(
                    "sort={},unicode={}",
                    u8::from(sort_keys),
                    u8::from(allow_unicode)
                );
                let Some(want) = case[&name].as_str() else {
                    continue;
                };
                checked += 1;
                let got = dump(
                    &value,
                    DumpOpts {
                        sort_keys,
                        allow_unicode,
                    },
                );
                if got != want {
                    failures.push(format!("{name} {value:?}\n  want {want:?}\n  got  {got:?}"));
                }
            }
        }
    }
    assert!(
        failures.is_empty(),
        "{} of {checked} dumps differ:\n{}",
        failures.len(),
        failures.join("\n")
    );
}

/// `load(dump(v)) == v` for every value of both corpora.
#[test]
fn dump_then_load_round_trips() {
    let mut values: Vec<Value> = serde_json::from_str::<Vec<serde_json::Value>>(CASES)
        .unwrap()
        .iter()
        .map(|c| common::decode(&c["value"]))
        .collect();
    values.extend(
        serde_json::from_str::<Vec<serde_json::Value>>(LOAD_CASES)
            .unwrap()
            .iter()
            .filter_map(|c| c.get("value").map(common::decode)),
    );
    for value in &values {
        for allow_unicode in [false, true] {
            let text = dump(
                value,
                DumpOpts {
                    sort_keys: false,
                    allow_unicode,
                },
            );
            if text.contains(['\u{85}', '\u{2028}', '\u{2029}']) {
                // Raw YAML 1.1 line breaks are refused by `load` (see lib docs).
                assert!(load(&text).is_err());
                continue;
            }
            let back = load(&text).unwrap_or_else(|e| panic!("{text:?}: {e}"));
            assert!(common::same(value, &back), "{text:?}\n{value:?}\n{back:?}");
        }
    }
}

#[test]
fn defaults_match_the_settings_writer() {
    let settings =
        load("context:\n  summary_trigger_tokens: 60.0\nname: café\nmode: 'off'\n").unwrap();
    assert_eq!(
        dump(&settings, DumpOpts::default()),
        "context:\n  summary_trigger_tokens: 60.0\nname: \"caf\\xE9\"\nmode: 'off'\n"
    );
}

#[test]
fn sorted_aware_timestamp_keys_follow_utc_across_midnight() {
    let value =
        load("2020-01-01 23:30:00-02:00: later\n2020-01-02 00:30:00+00:00: earlier\n").unwrap();
    assert_eq!(
        dump(
            &value,
            DumpOpts {
                sort_keys: true,
                allow_unicode: false,
            },
        ),
        "2020-01-02 00:30:00+00:00: earlier\n2020-01-01 23:30:00-02:00: later\n"
    );
}

#[test]
fn sorted_numeric_and_timestamp_keys_match_pyyaml() {
    let cases = [
        (
            "3: three\n1.5: float\ntrue: bool\n",
            "true: bool\n1.5: float\n3: three\n",
        ),
        (
            "2020-01-02: b\n2020-01-01: a\n",
            "2020-01-01: a\n2020-01-02: b\n",
        ),
        (
            "2020-01-01 12:00:00: b\n2020-01-01 09:15:00: a\n",
            "2020-01-01 09:15:00: a\n2020-01-01 12:00:00: b\n",
        ),
        (
            "2020-01-01 12:00:00+02:00: b\n2020-01-01 09:15:00+00:00: a\n",
            "2020-01-01 09:15:00+00:00: a\n2020-01-01 12:00:00+02:00: b\n",
        ),
    ];
    for (input, expected) in cases {
        let value = load(input).unwrap();
        assert_eq!(
            dump(
                &value,
                DumpOpts {
                    sort_keys: true,
                    allow_unicode: false
                }
            ),
            expected
        );
    }
}

#[test]
fn double_quoted_control_characters_match_pyyaml() {
    for (input, expected) in [
        ("\u{8}", "\"\\b\"\n"),
        ("\u{b}", "\"\\v\"\n"),
        ("\u{c}", "\"\\f\"\n"),
        ("\"\u{8}", "\"\\\"\\b\"\n"),
        ("\\\u{8}", "\"\\\\\\b\"\n"),
        ("\u{2029}", "\"\\P\"\n"),
    ] {
        assert_eq!(
            dump(&Value::Str(input.into()), DumpOpts::default()),
            expected
        );
    }
}
