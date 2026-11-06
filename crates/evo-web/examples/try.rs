//! `cargo run -p evo-web --example try -- search <query>` or `-- fetch <url>`.

#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("search") => {
            let q = evo_web::Query { query: args[1..].join(" "), max_results: 8, ..Default::default() };
            match evo_web::search(&q).await {
                Ok(results) => {
                    for (i, r) in results.iter().enumerate() {
                        println!("{}. {}\n   {}\n   {}", i + 1, r.title, r.url, r.snippet);
                    }
                }
                Err(e) => println!("error: {e}"),
            }
        }
        Some("fetch") => match evo_web::fetch(&args[1]).await {
            Ok(page) => {
                println!("{} → {} [{} {}] title={:?} cut={}", page.url, page.final_url, page.status, page.content_type, page.title, page.cut);
                println!("{} chars\n---\n{}", page.content.len(), page.content.chars().take(1500).collect::<String>());
            }
            Err(e) => println!("error: {e}"),
        },
        _ => println!("usage: try search <query> | try fetch <url>"),
    }
}
