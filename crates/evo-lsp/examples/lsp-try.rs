//! Try the language-server pieces from a terminal:
//!
//! ```text
//! cargo run -p evo-lsp --example lsp-try -- <lsp dir> <project> detect
//! cargo run -p evo-lsp --example lsp-try -- <lsp dir> <project> install <server id>
//! cargo run -p evo-lsp --example lsp-try -- <lsp dir> <project> diag <file>
//! cargo run -p evo-lsp --example lsp-try -- <lsp dir> <project> def|refs|hover <file> <line> <symbol>
//! cargo run -p evo-lsp --example lsp-try -- <lsp dir> <project> symbols <file>
//! ```

use std::path::PathBuf;

#[tokio::main]
async fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    if a.len() < 3 {
        println!("usage: lsp-try <lsp dir> <project> detect|install|diag|def|refs|hover|symbols …");
        return;
    }
    let lsp_dir = PathBuf::from(&a[0]);
    let cwd = PathBuf::from(&a[1]);
    let pool = evo_lsp::Pool::new(lsp_dir.clone());
    let out = match a[2].as_str() {
        "install" => {
            let server = evo_lsp::catalog::find(&a[3]).expect("unknown server id");
            evo_lsp::install::install(server, &lsp_dir, &|line| println!("  | {line}"))
                .await
                .map(|l| format!("installed: {} ({})", l.path.display(), l.source))
        }
        "detect" => Ok(format!("{:#?}", evo_lsp::detect::detect(&cwd))),
        "diag" => evo_lsp::ops::diagnostics(&pool, &cwd, Some(&a[3])).await,
        "symbols" => evo_lsp::ops::symbols(&pool, &cwd, &a[3]).await,
        op @ ("def" | "refs" | "hover") => {
            let op = match op {
                "def" => "definition",
                "refs" => "references",
                _ => "hover",
            };
            evo_lsp::ops::at(&pool, &cwd, op, &a[3], a[4].parse().unwrap_or(1), a.get(5).map(String::as_str), None).await
        }
        other => Err(format!("unknown command {other}")),
    };
    match out {
        Ok(text) => println!("{text}"),
        Err(e) => println!("ERROR: {e}"),
    }
    pool.stop(None).await;
}
