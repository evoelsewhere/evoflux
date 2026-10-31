//! `provider_parity <case.json> <base_url>`: run one provider parity case and
//! print its events as JSON. `contract-tests/providers` runs this for
//! `TARGET=rust`. Like `python_driver.py`, it points the case's provider at
//! `base_url` with the key `mock-key`.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::disallowed_methods)]

#[path = "../tests/common/mod.rs"]
mod common;

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    let (Some(case_path), Some(base_url)) = (args.get(1), args.get(2)) else {
        eprintln!("usage: provider_parity <case.json> <base_url>");
        std::process::exit(2);
    };
    let case: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(case_path).unwrap()).unwrap();
    let settings = common::settings_for(&case, base_url, std::env::vars().collect());
    let events = common::run_case(&case, &settings).await;
    println!("{}", serde_json::to_string(&events).unwrap());
}
