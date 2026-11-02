//! `parse_report`, `to_yaml` and `Section::validate` against Python's
//! `load_runtime_settings_report`, `save_runtime_settings` and pydantic, on
//! the corpus in `fixtures/gen_fixtures.py`.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use evoflux_shared_settings::*;
use evoflux_shared_yaml::Value;
use serde_json::Value as J;

const LOAD_CASES: &str = include_str!("fixtures/load_cases.json");
const SECTION_CASES: &str = include_str!("fixtures/section_cases.json");

#[test]
fn every_file_loads_and_saves_like_python() {
    let cases: Vec<J> = serde_json::from_str(LOAD_CASES).unwrap();
    assert!(cases.len() >= 60);
    let mut failures = Vec::new();
    for case in &cases {
        let text = case["yaml"].as_str().unwrap();
        match (parse_report(text), case.get("error")) {
            (Ok((settings, ignored)), None) => {
                let saved = settings.to_yaml();
                if saved != case["saved"].as_str().unwrap() {
                    failures.push(format!(
                        "{text:?}\n  saved want {:?}\n  saved got  {saved:?}",
                        case["saved"]
                    ));
                }
                let got: Vec<(String, String)> =
                    ignored.into_iter().map(|i| (i.field, i.message)).collect();
                let want: Vec<(String, String)> = case["ignored"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|p| {
                        (
                            p[0].as_str().unwrap().to_owned(),
                            p[1].as_str().unwrap().to_owned(),
                        )
                    })
                    .collect();
                if got != want {
                    failures.push(format!(
                        "{text:?}\n  ignored want {want:?}\n  ignored got  {got:?}"
                    ));
                }
            }
            (Err(error), Some(want)) => {
                let want = want.as_str().unwrap();
                let got = error.to_string();
                // The text after the prefix is PyYAML's own (lib docs).
                let prefix = |s: &str| s.split(':').next().unwrap_or_default().to_owned();
                if prefix(&got) != prefix(want) {
                    failures.push(format!(
                        "{text:?}\n  error want {want:?}\n  error got  {got:?}"
                    ));
                }
            }
            (Ok(_), Some(want)) => failures.push(format!("{text:?}\n  Python raised {want:?}")),
            (Err(e), None) => failures.push(format!("{text:?}\n  unexpected error {e}")),
        }
    }
    assert!(
        failures.is_empty(),
        "{} of {} differ:\n{}",
        failures.len(),
        cases.len(),
        failures.join("\n")
    );
}

fn section(name: &str, body: &Value) -> Result<J, Vec<ValidationError>> {
    use evoflux_shared_yaml::Mapping;
    fn ok<T: Section>(body: &Value) -> Result<Mapping, Vec<ValidationError>> {
        T::validate(body).map(|t| t.dump())
    }
    let dumped = match name {
        "title_generation" => ok::<TitleGenerationSettings>(body),
        "dream" => ok::<DreamSettings>(body),
        "memory_extraction" => ok::<MemoryExtractionSettings>(body),
        "git" => ok::<GitSettings>(body),
        "context" => ok::<ContextSettings>(body),
        "code_reviews" => ok::<CodeReviewSettings>(body),
        "webbridge" => ok::<WebBridgeSettings>(body),
        "computer_app" => ok::<ComputerAppSettings>(body),
        "import_auto_sync" => ok::<ImportAutoSyncSettings>(body),
        "conductor" => ok::<ConductorSettings>(body),
        "team_spawn" => ok::<TeamSpawnModeSettings>(body),
        "follow_up" => ok::<FollowUpSettings>(body),
        "background_tasks" => ok::<BackgroundTaskSettings>(body),
        "response_style" => ok::<ResponseStyleSettings>(body),
        "browser" => ok::<BuiltInBrowserSettings>(body),
        other => panic!("unknown section {other}"),
    }?;
    Ok(Value::Map(dumped).to_json())
}

#[test]
fn every_section_body_validates_like_pydantic() {
    let cases: Vec<J> = serde_json::from_str(SECTION_CASES).unwrap();
    let mut failures = Vec::new();
    for case in &cases {
        let name = case["section"].as_str().unwrap();
        let body = Value::from_json(&case["body"]);
        match (section(name, &body), case.get("dump")) {
            (Ok(got), Some(want)) => {
                // `model_dump(mode="json")` keeps None and excluded fields;
                // compare what both have.
                let want_obj = want.as_object().unwrap();
                for (key, value) in got.as_object().unwrap() {
                    if want_obj.get(key) != Some(value)
                        && !(value.is_f64()
                            && want_obj.get(key).and_then(J::as_f64) == value.as_f64())
                    {
                        failures.push(format!(
                            "{name} {body:?}: {key} want {:?} got {value:?}",
                            want_obj.get(key)
                        ));
                    }
                }
            }
            (Err(errors), None) => {
                let got: Vec<J> = errors
                    .iter()
                    .map(|e| {
                        let mut row = serde_json::json!({
                            "type": e.kind,
                            "loc": e.loc.iter().map(Loc::to_json).collect::<Vec<_>>(),
                            "msg": e.msg,
                        });
                        if let Some(ctx) = &e.ctx {
                            row["ctx"] = ctx.clone();
                        }
                        row
                    })
                    .collect();
                if J::Array(got.clone()) != case["errors"] {
                    failures.push(format!(
                        "{name} {body:?}\n  want {}\n  got  {}",
                        case["errors"],
                        J::Array(got)
                    ));
                }
            }
            (Ok(got), None) => failures.push(format!(
                "{name} {body:?}: pydantic refused it ({}), got {got}",
                case["errors"]
            )),
            (Err(errors), Some(_)) => {
                failures.push(format!("{name} {body:?}: unexpected errors {errors:?}"))
            }
        }
    }
    assert!(
        failures.is_empty(),
        "{} of {} differ:\n{}",
        failures.len(),
        cases.len(),
        failures.join("\n")
    );
}

#[test]
fn the_default_file_matches_python() {
    let cases: Vec<J> = serde_json::from_str(LOAD_CASES).unwrap();
    assert_eq!(
        RuntimeSettings::default().to_yaml(),
        cases[0]["saved"].as_str().unwrap()
    );
}
