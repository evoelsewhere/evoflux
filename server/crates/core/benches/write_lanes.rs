//! Repeatable lane comparison against copies of the committed v3 schema.
#![allow(clippy::disallowed_methods)]
use std::path::PathBuf;
use std::process::Command;

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
        for pattern in ["same-table", "cross-table"] {
            for writers in [1, 2, 4, 8] {
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
                println!(
                    "{}",
                    serde_json::json!({"mode":mode,"pattern":pattern,"writers":writers,"seconds":5,"result":value})
                );
            }
        }
    }
    Ok(())
}
