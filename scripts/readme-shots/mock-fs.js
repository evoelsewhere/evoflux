// README screenshots only (capture_app.py): a small fake repository for the
// Files tool and its git markers. Loaded after mock-tauri.js.
(() => {
  const ROOT = "C:\\Users\\demo\\code\\evo-harness";
  const HEAD_FETCH = `//! Fetch a public page as Markdown for the \`web_fetch\` tool.

use std::time::Duration;

use reqwest::{Client, Response, StatusCode};
use url::Url;

use crate::address::check_public;
use crate::page::Page;
use crate::{FetchError, Result};

/// Characters returned per call; the agent asks for the next slice.
pub const PAGE_CHARS: usize = 40_000;

/// The HTTP client every fetch shares: redirects are followed by hand so
/// each hop goes through \`check_public\`.
pub fn client() -> Client {
    Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(30))
        .user_agent(concat!("evo-web/", env!("CARGO_PKG_VERSION")))
        .build()
        .expect("static client configuration")
}

pub async fn fetch_page(client: &Client, url: &Url) -> Result<Page> {
    check_public(url)?;
    let response = client.get(url.clone()).send().await?;
    if !response.status().is_success() {
        return Err(FetchError::Status(response.status()));
    }
    Page::from_response(response).await
}
`;
  const RETRY = `
/// When a fetch tries again: rate limits and short outages only.
#[derive(Debug, Clone, Copy)]
pub struct RetryPolicy {
    pub max_attempts: u32,
    pub base_delay: Duration,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self { max_attempts: 3, base_delay: Duration::from_secs(1) }
    }
}

impl RetryPolicy {
    fn should_retry(&self, status: StatusCode, attempt: u32) -> bool {
        attempt + 1 < self.max_attempts
            && matches!(status, StatusCode::TOO_MANY_REQUESTS | StatusCode::SERVICE_UNAVAILABLE)
    }

    /// \`Retry-After\` in seconds when the site sends it, else 1 s, 2 s, 4 s.
    fn delay(&self, response: &Response, attempt: u32) -> Duration {
        response
            .headers()
            .get(reqwest::header::RETRY_AFTER)
            .and_then(|value| value.to_str().ok()?.parse().ok())
            .map(Duration::from_secs)
            .unwrap_or(self.base_delay * 2u32.pow(attempt))
    }
}

/// Retries 429 and 503 up to three times, waiting \`Retry-After\` or 1 s, 2 s, 4 s.
async fn send_with_retry(client: &Client, url: &Url, policy: RetryPolicy) -> Result<Response> {
    let mut attempt = 0;
    loop {
        let response = client.get(url.clone()).send().await?;
        if !policy.should_retry(response.status(), attempt) {
            return Ok(response);
        }
        tokio::time::sleep(policy.delay(&response, attempt)).await;
        attempt += 1;
    }
}
`;
  const NEW_FETCH = HEAD_FETCH.replace(
    "let response = client.get(url.clone()).send().await?;",
    "let response = send_with_retry(client, url, RetryPolicy::default()).await?;",
  ) + RETRY;

  const FILES = {
    "crates/evo-web/src/fetch.rs": { text: NEW_FETCH, base: HEAD_FETCH },
    "crates/evo-web/src/lib.rs": { text: "//! web_search and web_fetch.\n\npub mod address;\npub mod fetch;\npub mod page;\npub mod search;\n" },
    "crates/evo-web/Cargo.toml": { text: "[package]\nname = \"evo-web\"\nversion.workspace = true\n" },
    "README.md": { text: "# Evo Harness\n" },
  };
  const TREE = {
    "": ["apps/", "crates/", "docs/", "examples/", "scripts/", ".gitignore", "AGENTS.md", "Cargo.lock", "Cargo.toml", "DESIGN.md", "LICENSE", "NOTICE", "README.md"],
    "crates": ["evo-agent/", "evo-ai/", "evo-engine/", "evo-harness/", "evo-mcp/", "evo-protocol/", "evo-runtime/", "evo-store/", "evo-tools/", "evo-web/"],
    "crates/evo-web": ["src/", "tests/", "Cargo.toml", "README.md"],
    "crates/evo-web/src": ["address.rs", "fetch.rs", "lib.rs", "page.rs", "search.rs"],
  };

  const rel = (path) => {
    let p = String(path || "").replace(/\//g, "\\");
    if (p.toLowerCase().startsWith(ROOT.toLowerCase())) p = p.slice(ROOT.length);
    return p.replace(/^\\+|\\+$/g, "").replace(/\\/g, "/");
  };
  const abs = (r) => (r ? `${ROOT}\\${r.replace(/\//g, "\\")}` : ROOT);
  const mtime = Date.now() - 60_000;

  Object.assign(window.__mockHandlers, {
    fs_list_dir: ({ path }) => {
      const r = rel(path);
      return (TREE[r] || []).map((name) => {
        const dir = name.endsWith("/");
        const clean = dir ? name.slice(0, -1) : name;
        const child = r ? `${r}/${clean}` : clean;
        return { name: clean, path: abs(child), dir, size: dir ? 0 : (FILES[child]?.text.length ?? 2048), dimmed: clean.startsWith(".") };
      });
    },
    fs_stat: ({ path }) => {
      const r = rel(path);
      const dir = r === "" || r in TREE;
      return { exists: dir || r in FILES || true, dir, size: FILES[r]?.text.length ?? 0, mtime };
    },
    fs_read_file: ({ path }) => {
      const r = rel(path);
      const text = FILES[r]?.text ?? `// ${r}\n`;
      return { kind: "text", text, size: text.length, mtime, lossy: false };
    },
    git_status: () => ({
      root: ROOT, branch: "feat/web-fetch-retry", head: "25f5113", upstream: "origin/feat/web-fetch-retry", ahead: 1, behind: 0,
      files: [{ path: "crates/evo-web/src/fetch.rs", status: "modified", added: 47, removed: 1 }, { path: "crates/evo-web/tests/retry.rs", status: "added", added: 64, removed: 0 }],
      added: 111, removed: 1,
    }),
    git_ignored: () => [`${ROOT.replace(/\\/g, "/")}/target`],
    git_file_base: ({ path }) => FILES[rel(path)]?.base ?? FILES[rel(path)]?.text ?? null,
  });
})();
