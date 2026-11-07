# Web search and web fetch

| | |
| --- | --- |
| Status | Implemented (layers 1–2); layer 3 proposed |
| Area | crate `evo-web`, engine |
| Format | Legacy — predates [the SDD template](../../templates/sdd.md); move to it on the next substantial edit |
| Updated | 2026-11-06 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view) |
| ADRs | none |

Status: layers 1 and 2 are built (2026-11-06) — `web_fetch`, and `web_search`
through a keyless chain (DuckDuckGo's HTML page, then Exa's hosted MCP
server, then Wikipedia); keyed backends (Brave, Tavily, …) and layer 3 (the
provider's own search) are not.

## Built

- `crates/evo-web`: `guard` (public addresses only: a DNS resolver that drops
  private, loopback, link-local, CGNAT, multicast, documentation and
  metadata addresses, IPv4-mapped / NAT64 / 6to4 unwrapped; IP literals,
  schemes, credentials and `localhost` checked on every redirect hop),
  `fetch` (http(s), 5 redirects, 20 s, 5 MB, no cookies, no proxy, charset
  from the header or `<meta>`, 15-minute cache; HTML → Markdown, text / JSON
  / XML as they are; PDFs and other binaries refused with a pointer to the
  browser), `extract` (the article, main region or body, without navigation,
  scripts, forms, images; links absolute; empty links dropped), `search`
  (a chain of keyless backends tried in order, as evo v3 did; the first
  with results after the domain filter answers, a failed or paused one is
  skipped, and the error lists every backend's failure only when all fail;
  10-minute cache keyed on the normalised query, limits and result count;
  snippets cut at 3,000 characters):
  - `search::duckduckgo`: POST `https://html.duckduckgo.com/html/` with
    evo's own user agent (no browser impersonation); `site:` / `-site:` for
    domain limits; `df` for recency; ads skipped; redirect links decoded; at
    least 1.5 s between requests; a block page (202 / 403 / 429 / the
    "unusual traffic" check) pauses this backend for 90 s, and searches
    queued behind it skip it without sending a request. DuckDuckGo often
    answers the first request with 202.
  - `search::exa`: Exa's hosted MCP server (`https://mcp.exa.ai/mcp`, tool
    `web_search_exa`, no key; one stateless `tools/call`; the reply is JSON
    or server-sent events). Its tool takes `query`, `numResults` and a
    required `objective`; domain limits and the period go into the objective
    in words, and the results are still filtered. Entries are parsed from
    `Title: / URL: / Published: / Highlights:` text; the date leads the
    snippet. HTTP 429 or a "rate limit" answer pauses it for 60 s. Exa does
    not publish the free limit.
  - `search::wikipedia`: English Wikipedia's search API (`list=search`),
    skipped when the query has a period or domain limits other than
    Wikipedia.
  - Not carried over from v3: its `ddgs` library (which impersonates a
    browser to pass bot checks), the `brave` and `mojeek` HTML backends, and
    the redaction of secrets in the query before it leaves the machine.
  `cargo run -p evo-web --example try -- search <query>` runs the chain;
  `-- exa <query>` / `-- wikipedia <query>` one backend; `-- fetch <url>`.
- Engine (`crates/evo-engine/src/web_tools.rs`): tools `web_search {query,
  max_results?, allowed_domains?, blocked_domains?, recency?}` and
  `web_fetch {url, offset?}` (40,000 characters per call, the page wrapped in
  `<web_page url title>` and described as data, never instructions).
  `webTools: false` in settings leaves both out. They run without approval,
  like `read`. `web_search`'s details carry `source` (the backend that
  answered).
- Desktop: "Searched the web · query" with the results as links (they open
  in the browser), "Read · host/path" with the page text.
- Checked with a real model: it searched, read the official page, and
  answered with the source URL.
- DuckDuckGo has no official web-search API; this reads the page meant for
  browsers without JavaScript, with an honest user agent and low volume. It
  can stop working if the page changes or DuckDuckGo limits it. Exa's
  keyless server has an unpublished limit and Wikipedia finds articles only;
  when every backend fails the tool says so, and the browser tools remain.
  A keyed backend (layer 2 below) is still the durable fix.
- Queries go to DuckDuckGo, Exa and Wikipedia as typed (third parties).
- A network that filters traffic (a company proxy) can answer with its own
  block page; `web_fetch` returns it as an HTTP error.

## Where evo is today

- No web tool is built in. `websearch` and `webfetch` exist as optional
  extensions in the separate `evo-package` repository (`evo install
  evo-websearch`, `evo install evo-webfetch`); the desktop app installs
  neither, so its chats cannot search or read the web except through the
  in-app browser tools (`browser_*`, a real browser the agent drives).
- The transcript already labels `web_search` / `web_fetch` as "web" rows
  (`components/ai-elements/tool.tsx`), so the names are reserved.
- `evo-ai` content blocks are `Text`, `Thinking`, `Image`, `ToolCall`
  (`crates/evo-ai/src/types.rs`); the Anthropic mapper drops other block
  types. A provider's own search (below) returns blocks that must be sent
  back unchanged on the next turn, so it cannot work until `evo-ai` carries
  such blocks through.

## How others do it

### The model provider searches (server-side tools)

| Provider | Tools | Notes |
| --- | --- | --- |
| Anthropic Messages API | `web_search` (`web_search_20250305`, `_20260209`, `_20260318`), `web_fetch` (`web_fetch_20250910`, `_20260209`, `_20260309`, `_20260318`) | Runs on the provider. Params: `max_uses`, `allowed_domains` **or** `blocked_domains`, `user_location` (search), `citations`, `max_content_tokens`, `use_cache`, `url_sources` (fetch). Blocks: `server_tool_use`, `web_search_tool_result` (results carry `encrypted_content`), `web_fetch_tool_result` (a `document`; PDFs as base64). Errors come as result blocks with `error_code` (HTTP 200). Every block must be returned unchanged on the next turn. Search is $10 per 1,000 plus tokens; fetch costs tokens only. Fetch only opens URLs already in the conversation (user input, tool results, earlier search results). The 2026-02 versions add "dynamic filtering": the model filters results with code execution before they enter its context (more accurate, fewer tokens); `allowed_callers: ["direct"]` opts out. Streams as `server_tool_use` + `input_json_delta`, then a result block; long turns can stop with `pause_turn`. |
| OpenAI Responses API | `web_search` (`web_search_preview` is legacy) | `filters.allowed_domains` (up to 20), `search_context_size`, `user_location`, `return_token_budget`; answers carry URL citations. |
| Gemini API | `google_search` (grounding), `url_context` | Grounding returns citations and the queries run; `url_context` reads given URLs; both can be combined. Daily quotas apply. |

Pros: best result quality, no key to manage, citations. Cons: per provider,
different shapes, costs per search, blocks to round-trip, and only for
models that support it.

### The agent searches (client-side tools)

- **Search backends** for agents (prices vary; check before choosing):
  Brave Search API (own index; about $5 per 1,000, no free tier since
  2026-02), Tavily (credits; ~1,000 free a month; AI-ready snippets), Exa
  (semantic search with page text; ~$7 per 1,000), Serper (Google results,
  cheap), self-hosted SearXNG (free, needs a server). Jina Reader and
  Firecrawl turn pages into clean text.
- **Coding agents**: OpenCode's `webfetch` downloads the page and converts
  HTML to Markdown; its `websearch` calls Exa's hosted MCP server; both ask
  permission first. Gemini CLI's `google_web_search` returns a summary with
  citations from the Gemini API; its `web_fetch` takes a prompt with up to
  20 URLs, asks before fetching, reads them through `url_context`, and falls
  back to fetching locally. Codex CLI's `web_search` is `cached` (a provider
  index, default), `live`, or `disabled`.
- **Fetch safety** (recent CVEs in agent frameworks): block private,
  loopback, link-local and metadata addresses **after DNS resolution and on
  every redirect hop** (not by matching the URL text); treat IPv4-mapped
  IPv6 as IPv4; cap size and time; never send cookies or credentials; treat
  the page as untrusted data (prompt injection), not instructions.

## Proposal for evo

Three layers; build them in this order.

### 1. Built-in `web_fetch` (engine, every model)

`crates/evo-tools` (or `evo-engine`), a normal tool next to `read`:

- Input: `url`, optional `offset` (characters, for long pages), optional
  `raw` (skip extraction).
- Network: `reqwest`, http and https only, at most 5 redirects; each hop's
  host is resolved and every address checked (no private, loopback,
  link-local, CGNAT, multicast, metadata `169.254.169.254`, or IPv4-mapped
  forms); the connection pins the checked address (no DNS rebinding). 20 s
  timeout, 5 MB body cap, a plain user agent, no cookies.
- Content: HTML → the main article as Markdown (readability-style
  extraction, links kept, scripts and navigation dropped); JSON and text as
  they are; PDF → text; images refused (point to the browser). Output cut at
  about 40k characters with "continue with offset N".
- Result wrapped as untrusted (`<web_page url=… fetched_at=…>`), with a line
  in the tool description that page text is data, never instructions.
- 15-minute in-memory cache per URL.
- Permission like connectors: per domain Allow / Ask / Block, default Ask
  for a domain not seen before in the chat, with "Always allow this domain"
  (saved in settings). Settings can switch the tool off.

### 2. Built-in `web_search` with a choice of backend

- Input: `query`, optional `max_results` (default 8), `allowed_domains`,
  `blocked_domains`, `recency` (day, week, month, year).
- Output: numbered results — title, URL, snippet, date — and an instruction
  to cite the URLs used. Results feed `web_fetch` for detail.
- Backends behind one trait: Brave, Tavily, Exa, Serper, SearXNG (a URL).
  The key lives with the other credentials (hot-reloaded, no restart).
  No backend configured → the tool is not offered, and Settings says why.
- Settings → Web: backend, key, a "Test" button, the fetch domain list.

### 3. The provider's own search, when the model has it

- `evo-ai`: a new opaque block (`ProviderBlock { provider, raw }`) that the
  mapper keeps in order and sends back unchanged; citations parsed into a
  common shape for the UI. Handle `pause_turn` (resend and continue).
- When the chosen model supports it (models.dev data where available, else
  a per-provider list), and Settings → Web → "Use the model's own search"
  is on, send the provider's tool instead of (or beside) layer 2.
- Costs show in the turn's usage (`server_tool_use.web_search_requests`).

### In the app

- Transcript: "Searched the web · query" with the result list (favicon,
  domain, title); "Read · domain/path" with the extracted text; citations as
  numbered chips linking to sources.
- The in-app browser stays the tool for pages that need JavaScript, login
  or clicking; `web_fetch` errors on such pages say so.

## Open questions

- Which search backend to recommend by default (cost vs. quality), and
  whether a backend without a key (SearXNG instance) should be bundled.
- Whether `web_fetch` should optionally summarise a long page with a small
  model against a question, to save context.
- Domain permissions: per chat, per project, or global.
