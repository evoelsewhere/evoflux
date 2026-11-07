//! `cargo run -p evo-web --example try -- search <query>` (the whole chain),
//! `-- exa <query>` / `-- wikipedia <query>` (one backend), or `-- fetch <url>`.

use evo_web::search::{exa, wikipedia};
use evo_web::SearchResult;

fn print(results: &[SearchResult]) {
    for (i, r) in results.iter().enumerate() {
        let snippet: String = r.snippet.chars().take(300).collect();
        println!("{}. {}\n   {}\n   {}", i + 1, r.title, r.url, snippet.replace('\n', " "));
    }
}

#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let q = evo_web::Query { query: args.get(1..).unwrap_or_default().join(" "), max_results: 8, ..Default::default() };
    match args.first().map(String::as_str) {
        Some("search") => match evo_web::search(&q).await {
            Ok(found) => {
                println!("from {}", found.source);
                print(&found.results);
            }
            Err(e) => println!("error: {e}"),
        },
        Some("exa") => match exa::search(&q, 8).await {
            Ok(results) => print(&results),
            Err(e) => println!("error: {e}"),
        },
        Some("wikipedia") => match wikipedia::search(&q.query, 8).await {
            Ok(results) => print(&results),
            Err(e) => println!("error: {e}"),
        },
        Some("fetch") => match evo_web::fetch(&args[1]).await {
            Ok(page) => {
                println!("{} → {} [{} {}] title={:?} cut={}", page.url, page.final_url, page.status, page.content_type, page.title, page.cut);
                println!("{} chars\n---\n{}", page.content.len(), page.content.chars().take(1500).collect::<String>());
            }
            Err(e) => println!("error: {e}"),
        },
        _ => println!("usage: try search|exa|wikipedia <query> | try fetch <url>"),
    }
}
