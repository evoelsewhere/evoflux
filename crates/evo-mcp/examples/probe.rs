//! Connect to one MCP server and list what it offers, through the same pool
//! the app uses (with a throwaway connectors file).
//!
//! cargo run -p evo-mcp --example probe -- <command> [args…]
//! cargo run -p evo-mcp --example probe -- https://example.com/mcp

use evo_mcp::{Pool, ServerConfig};

#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(first) = args.first() else {
        eprintln!("usage: probe <command> [args…] | <url>");
        std::process::exit(2);
    };
    let config = if first.starts_with("http://") || first.starts_with("https://") {
        ServerConfig {
            url: Some(first.clone()),
            ..Default::default()
        }
    } else {
        ServerConfig {
            command: Some(first.clone()),
            args: args[1..].to_vec(),
            ..Default::default()
        }
    };
    let dir = std::env::temp_dir().join(format!("evo-mcp-probe-{}", std::process::id()));
    let pool = Pool::new(dir.join("mcp.json"), None, || {});
    pool.start().expect("empty config");
    pool.upsert("probe", config, None)
        .await
        .expect("valid config");
    let snapshot = pool.snapshot();
    let server = &snapshot["servers"][0];
    println!("status: {}  error: {}", server["status"], server["error"]);
    println!("server: {}", server["server"]);
    let tools = server["tools"].as_array().cloned().unwrap_or_default();
    println!("{} tools:", tools.len());
    for tool in &tools {
        println!(
            "  {:30} {:5} {}",
            tool["name"].as_str().unwrap_or(""),
            tool["permission"].as_str().unwrap_or(""),
            tool["exposedName"]
        );
    }
    let prompts = server["prompts"].as_array().cloned().unwrap_or_default();
    println!(
        "{} prompts: {:?}",
        prompts.len(),
        prompts
            .iter()
            .map(|p| p["name"].clone())
            .collect::<Vec<_>>()
    );
    if tools.iter().any(|t| t["name"] == "echo") {
        let mut args = serde_json::Map::new();
        args.insert("message".into(), "hello from evo".into());
        match pool.call("mcp__probe__echo", Some(args), None).await {
            Ok(result) => println!("echo → {}", result["content"]),
            Err(error) => println!("echo failed: {error}"),
        }
    }
    pool.shutdown().await;
    let _ = std::fs::remove_dir_all(dir);
}
