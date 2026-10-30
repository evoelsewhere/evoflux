//! Repeatable lane comparison against copies of the committed v3 schema.
//! Each cell runs `RUNS` times; the row reports the medians and every run.
#![allow(clippy::disallowed_methods)]
use std::path::PathBuf;
use std::process::Command;

const RUNS: usize = 3;

fn median(mut values: Vec<f64>) -> f64 {
    values.sort_by(f64::total_cmp);
    values.get(values.len() / 2).copied().unwrap_or(0.0)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let root = manifest
        .parent()
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .ok_or("workspace root missing")?;
    let fixture = root.join("contract-tests/fixtures/upgrade/v3.0.0/evoflux.db");
    let target = std::env::var_os("CARGO_TARGET_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("server/target"));
    let target = if target.is_absolute() {
        target
    } else {
        root.join("server").join(target)
    };
    let binary = target.join("release/examples").join(if cfg!(windows) {
        "db_stress.exe"
    } else {
        "db_stress"
    });
    if !binary.is_file() {
        return Err(
            "build first: cargo build -p evoflux-core --release --example db_stress".into(),
        );
    }
    for mode in ["fifo", "concurrent"] {
        for pattern in ["same-table", "cross-table", "message"] {
            for writers in [1, 2, 4, 8] {
                let mut runs = Vec::new();
                for _ in 0..RUNS {
                    let dir = tempfile::tempdir()?;
                    let db = dir.path().join("bench.db");
                    std::fs::copy(&fixture, &db)?;
                    let output = Command::new(&binary)
                        .args([
                            "--db",
                            db.to_str().ok_or("non UTF-8 path")?,
                            "--seconds",
                            "5",
                            "--writers",
                            &writers.to_string(),
                            "--report",
                            "json",
                            "--mode",
                            mode,
                            "--pattern",
                            pattern,
                        ])
                        .output()?;
                    if !output.status.success() {
                        return Err(format!(
                            "{mode} {pattern} {writers}: {}",
                            String::from_utf8_lossy(&output.stderr)
                        )
                        .into());
                    }
                    let value: serde_json::Value = serde_json::from_slice(&output.stdout)?;
                    runs.push(value);
                }
                let field = |key: &str| -> Vec<f64> {
                    runs.iter()
                        .map(|r| {
                            r.get(key)
                                .and_then(serde_json::Value::as_f64)
                                .unwrap_or(0.0)
                        })
                        .collect()
                };
                let rates: Vec<f64> = runs
                    .iter()
                    .map(|r| {
                        r.get("acknowledged")
                            .and_then(serde_json::Value::as_f64)
                            .unwrap_or(0.0)
                            / r.get("elapsed_seconds")
                                .and_then(serde_json::Value::as_f64)
                                .unwrap_or(1.0)
                    })
                    .collect();
                println!(
                    "{}",
                    serde_json::json!({"mode": mode, "pattern": pattern, "writers": writers, "seconds": 5,
                        "writes_per_second": median(rates), "p99_ms": median(field("p99_ms")),
                        "transaction_retries": median(field("transaction_retries")),
                        "busy_retries": median(field("busy_retries")),
                        "wal_max_bytes": field("wal_max_bytes").into_iter().fold(0.0, f64::max),
                        "runs": runs})
                );
            }
        }
    }
    Ok(())
}
