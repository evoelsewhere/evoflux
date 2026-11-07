# Web search and web fetch — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view) |
| ADRs | none |

## 1. Context and constraints

### 1.1 What evo had before

- No web tool was built in. `websearch` and `webfetch` existed as optional
  extensions in the separate `evo-package` repository (`evo install
  evo-websearch`, `evo install evo-webfetch`); the desktop app installed
  neither, so its chats could not search or read the web except through the
  in-app browser tools (`browser_*`, a real browser the agent drives).
- The transcript already labelled `web_search` / `web_fetch` as "web" rows
  (`apps/desktop/src/components/ai-elements/tool.tsx`), so the names were
  reserved.
- `evo-ai` content blocks are `Text`, `Thinking`, `Image`, `ToolCall`
  (`crates/evo-ai/src/types.rs`); the Anthropic mapper drops other block
  types. A provider's own search (layer 3) returns blocks that must be sent
  back unchanged on the next turn, so it cannot work until `evo-ai` carries
  such blocks through.
- evo v3 searched through a chain of keyless backends; this design follows
  it, except for what section 4 lists as not carried over.

### 1.2 The model provider searches (server-side tools)

| Provider | Tools | Notes |
| --- | --- | --- |
| Anthropic Messages API | `web_search` (`web_search_20250305`, `_20260209`, `_20260318`), `web_fetch` (`web_fetch_20250910`, `_20260209`, `_20260309`, `_20260318`) | Runs on the provider. Params: `max_uses`, `allowed_domains` **or** `blocked_domains`, `user_location` (search), `citations`, `max_content_tokens`, `use_cache`, `url_sources` (fetch). Blocks: `server_tool_use`, `web_search_tool_result` (results carry `encrypted_content`), `web_fetch_tool_result` (a `document`; PDFs as base64). Errors come as result blocks with `error_code` (HTTP 200). Every block must be returned unchanged on the next turn. Search is $10 per 1,000 plus tokens; fetch costs tokens only. Fetch only opens URLs already in the conversation (user input, tool results, earlier search results). The 2026-02 versions add "dynamic filtering": the model filters results with code execution before they enter its context (more accurate, fewer tokens); `allowed_callers: ["direct"]` opts out. Streams as `server_tool_use` + `input_json_delta`, then a result block; long turns can stop with `pause_turn`. |
| OpenAI Responses API | `web_search` (`web_search_preview` is legacy) | `filters.allowed_domains` (up to 20), `search_context_size`, `user_location`, `return_token_budget`; answers carry URL citations. |
| Gemini API | `google_search` (grounding), `url_context` | Grounding returns citations and the queries run; `url_context` reads given URLs; both can be combined. Daily quotas apply. |

Pros: best result quality, no key to manage, citations. Cons: per provider,
different shapes, costs per search, blocks to round-trip, and only for
models that support it.

### 1.3 The agent searches (client-side tools)

- **Search backends** for agents (prices vary; check before choosing):
  Brave Search API (own index; about $5 per 1,000, no free tier since
  2026-02), Tavily (credits; ~1,000 free a month; AI-ready snippets), Exa
  (semantic search with page text; ~$7 per 1,000), Serper (Google results,
  cheap), self-hosted SearXNG (free, needs a server). Jina Reader and
  Firecrawl turn pages into clean text.
- **Other coding agents**: one open-source agent's `webfetch` downloads the
  page and converts HTML to Markdown, and its `websearch` calls Exa's hosted
  MCP server; both ask permission first. A command-line agent built on the
  Gemini API has a `google_web_search` that returns a summary with citations
  from the Gemini API, and a `web_fetch` that takes a prompt with up to 20
  URLs, asks before fetching, reads them through `url_context`, and falls
  back to fetching locally. Another command-line agent's `web_search` is
  `cached` (a provider index, default), `live`, or `disabled`.
- **Fetch safety** (recent CVEs in agent frameworks): block private,
  loopback, link-local and metadata addresses **after DNS resolution and on
  every redirect hop** (not by matching the URL text); treat IPv4-mapped IPv6
  as IPv4; cap size and time; never send cookies or credentials; treat the
  page as untrusted data (prompt injection), not instructions.

### 1.4 External constraints

- DuckDuckGo has no official web-search API; evo reads the page meant for
  browsers without JavaScript, with an honest user agent and low volume. It
  can stop working if the page changes or DuckDuckGo limits it. DuckDuckGo
  often answers the first request with 202.
- Exa's keyless server has an unpublished limit, and Exa does not publish the
  free limit.
- Wikipedia finds articles only.
- When every backend fails the tool says so, and the browser tools remain. A
  keyed backend (layer 2, FR-9) is still the durable fix.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | Both tools run in the engine; the desktop only renders them. |
| Layers point down; library crates stay free of engine/desktop concerns | ok | `evo-web` knows HTTP, HTML and the search backends, nothing about the agent; `evo-engine/src/web_tools.rs` adapts it to `AgentTool`. Layer 3 would add an opaque block to `evo-ai` without provider wire formats leaking above it. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | n/a | Ordinary tool calls; no protocol change. |
| Models come from models.dev; no hardcoded model facts | ok | Layer 3 (proposed) reads provider-search support from models.dev data where available, else a per-provider list. |
| Real engine in the app; settings and credentials reload live | ok | `webTools` is read from settings when tools are built; proposed keys live with the other credentials and hot-reload. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | Pages are wrapped and described as data; only public addresses are reachable. Both tools run without approval, like `read` (per-domain permission is proposed, FR-10). |
| Desktop UI structure and `DESIGN.md` | ok | Rendering is a tool kind in the existing `tool.tsx`. |

## 3. Design

### 3.1 Overview

```text
 model ──► web_search ──► search chain ──► duckduckgo ─(no results / failed / paused)─► exa ──► wikipedia
   │                         │ 10-min cache, domain filter, snippet clip
   │
   └────► web_fetch ──► guard (scheme, host, DNS: public addresses only, every hop)
                          └► fetch (≤5 redirects, 20 s, 5 MB, charset, 15-min cache)
                               └► extract (HTML → Markdown) ──► <web_page url title> window of 40,000 chars
```

Three layers, built in this order: (1) a built-in `web_fetch` for every
model; (2) a built-in `web_search` — built as a keyless chain, keyed
backends proposed; (3) the provider's own search when the model has it
(proposed).

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| crate | `crates/evo-web/src/guard.rs` | Public addresses only: a DNS resolver that drops private, loopback, link-local, CGNAT, multicast, documentation and metadata (`169.254.169.254`) addresses, unwrapping IPv4-mapped / NAT64 / 6to4; IP literals, schemes, credentials and `localhost` checked on every redirect hop | FR-2 |
| crate | `crates/evo-web/src/fetch.rs` | http(s), 5 redirects, 20 s, 5 MB, no cookies, no proxy, charset from the header or `<meta>`, 15-minute cache; HTML → Markdown, text / JSON / XML as they are; PDFs and other binaries refused | FR-1, FR-6, NFR-1 |
| crate | `crates/evo-web/src/extract.rs` | The article, main region or body, without navigation, scripts, forms, images; links absolute; empty links dropped | FR-1 |
| crate | `crates/evo-web/src/search.rs` | The keyless chain, domain filter, 10-minute cache, snippet clip at 3,000 characters, pauses | FR-4, FR-5, FR-6, NFR-3 |
| crate | `crates/evo-web/src/search/duckduckgo.rs` | DuckDuckGo HTML backend | FR-5, NFR-3 |
| crate | `crates/evo-web/src/search/exa.rs` | Exa hosted MCP backend | FR-5, NFR-3 |
| crate | `crates/evo-web/src/search/wikipedia.rs` | Wikipedia search API backend | FR-5 |
| crate | `crates/evo-web/examples/try.rs` | Manual runner: `cargo run -p evo-web --example try -- search <query>` runs the chain; `-- exa <query>` / `-- wikipedia <query>` one backend; `-- fetch <url>` | FR-1, FR-5 |
| engine | `crates/evo-engine/src/web_tools.rs` | The `web_search` and `web_fetch` tools: schemas, windows, the page wrapper, `details` | FR-1, FR-3, FR-4, FR-7 |
| engine | `crates/evo-engine/src/session.rs`, `crates/evo-engine/src/settings.rs` | Registers both tools unless `webTools` is `false` | FR-7 |
| desktop UI | `apps/desktop/src/components/ai-elements/tool.tsx` | "Searched the web · query" with result links; "Read · host/path" with the page text | FR-8 |
| crate | `crates/evo-ai` *(proposed)* | Opaque provider block, citations, `pause_turn` | FR-11 |
| desktop UI | **Settings → Web** *(proposed)* | Backend, key, **Test**, fetch domain list, **Use the model's own search** | FR-9, FR-10, FR-11 |

### 3.3 Interfaces

**`web_search`** (model-facing):

```jsonc
{
  "query": "…",                      // required; as you would type it
  "max_results": 8,                  // 1–20, default 8
  "allowed_domains": ["docs.rs"],    // only these sites
  "blocked_domains": ["…"],
  "recency": "week"                  // day | week | month | year
}
```

The description tells the model to read a result with `web_fetch` before
relying on it, to cite the URLs it uses, and to use the browser tools for
pages that need JavaScript or a login. Output: numbered results — title,
URL, snippet, date. `details.source` names the backend that answered.

**`web_fetch`** (model-facing):

```jsonc
{
  "url": "https://…",   // required; https:// is added when missing
  "offset": 0           // character to start from, default 0
}
```

Result text:

```text
<web_page url="<final url>" title="<title>">
…up to 40,000 characters…
</web_page>
[Characters 0–40000 of 91234. Call web_fetch with offset 40000 for the rest.]
```

An empty page reads "(no readable text: the page may need JavaScript — try
the browser tools)"; a cut body adds "[The page was larger than 5 MB; only
the start was read.]". `details`: `url`, `finalUrl`, `title`,
`contentType`, `status`, `chars`, `offset`, `end`.

**Backends:**

- `search::duckduckgo`: POST `https://html.duckduckgo.com/html/` with evo's
  own user agent (no browser impersonation); `site:` / `-site:` for domain
  limits; `df` for recency; ads skipped; redirect links decoded.
- `search::exa`: Exa's hosted MCP server (`https://mcp.exa.ai/mcp`, tool
  `web_search_exa`, no key; one stateless `tools/call`; the reply is JSON or
  server-sent events). Its tool takes `query`, `numResults` and a required
  `objective`; domain limits and the period go into the objective in words,
  and the results are still filtered. Entries are parsed from `Title: / URL:
  / Published: / Highlights:` text; the date leads the snippet.
- `search::wikipedia`: English Wikipedia's search API (`list=search`).

**Proposed interfaces:**

- Keyed backends behind one trait: Brave, Tavily, Exa, Serper, SearXNG (a
  URL).
- `evo-ai`: a new opaque block `ProviderBlock { provider, raw }` that the
  mapper keeps in order and sends back unchanged; citations parsed into a
  common shape for the UI; `pause_turn` handled (resend and continue). Costs
  from `server_tool_use.web_search_requests` go into the turn's usage.

### 3.4 Data and storage

- In-memory caches in the engine process: fetched pages 15 minutes per URL;
  searches 10 minutes keyed on the normalised query, limits and result
  count. Backend pauses are in memory too. Nothing is written to disk.
- *(Proposed)* backend keys with the other credentials; the fetch domain
  list and **Always allow** entries in settings.

### 3.5 Behaviour

**Fetch.** Check the URL (scheme, credentials, IP literal, `localhost`),
resolve the host through the guard's resolver, request with `reqwest`, no cookies and
no proxy, and repeat the checks on each redirect hop (at most 5). Read up to
5 MB within 20 s; decode with the charset from the header or `<meta>`. HTML
goes through `extract` and becomes Markdown; text, JSON and XML pass as they
are; PDFs and other binaries are refused. The engine returns a 40,000
character window from `offset`, wrapped as in 3.3.

**Search.** Normalise the query and check the cache. Try each backend in
order; skip a paused one without a request; drop results outside the domain
limits; the first backend with results answers. Wikipedia is skipped when
the query has a period or domain limits other than Wikipedia. Snippets are
cut at 3,000 characters on a character boundary.

**Pauses.** DuckDuckGo: at least 1.5 s between requests; a block page (202 /
403 / 429 / the "unusual traffic" check) pauses it for 90 s, and searches
queued behind it skip it without sending a request. Exa: HTTP 429 or a "rate
limit" answer pauses it for 60 s.

**Layer 3 (proposed).** When the chosen model supports provider search
(models.dev data where available, else a per-provider list) and **Settings →
Web → Use the model's own search** is on, send the provider's tool instead
of (or beside) layer 2, carry its blocks through unchanged, and show its
citations as numbered chips.

### 3.6 Errors and edge cases

- All backends fail → the error lists every backend's failure; the browser
  tools remain.
- A network that filters traffic (a company proxy) can answer with its own
  block page; `web_fetch` returns it as an HTTP error.
- Private or special address, bad scheme, credentials in the URL → refused
  before any request.
- PDF → "this is a PDF; web_fetch reads web pages and text. Open it in the
  browser, or download it and read the file"; other binaries → open it in the
  browser instead.
- `offset` past the end → a validation error.
- Cancellation → the call ends with "cancelled".

### 3.7 Security and trust

- Page text is untrusted: wrapped in `<web_page …>` and the tool
  description says never to follow instructions written in it.
- Fetch reaches public addresses only, checked after DNS resolution and on
  every redirect hop (FR-2); no cookies, no proxy, no credentials sent.
- Both tools run without approval, like `read`. Per-domain permission (like connectors) is
  proposed (FR-10).
- Queries go to DuckDuckGo, Exa and Wikipedia as typed (third parties).
  Secrets in a query are not redacted (v3 did this; not carried over).
- `webTools: false` removes both tools.

### 3.8 Configuration

| Key | Type, default | Where | Applies |
| --- | --- | --- | --- |
| `webTools` | bool, `true` | settings | when tools are built |
| *(Proposed)* **Settings → Web**: backend, key, **Test** | choice, secret | settings, credentials | live (hot-reloaded) |
| *(Proposed)* fetch domain list (Allow / Ask / Block) | per domain | settings | live |
| *(Proposed)* **Use the model's own search** | bool | settings | next turn |

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| Only the provider's own search | Per provider, different shapes, costs per search, blocks to round-trip, and only for models that support it; kept as layer 3. |
| Only keyed backends ("no backend configured → the tool is not offered", the original layer 2) | Chats would have no search out of the box; the keyless chain works with nothing configured, and keyed backends stay proposed. |
| The `ddgs` library v3 used (it impersonates a browser to pass bot checks) | Not carried over: evo uses its own user agent. |
| v3's `brave` and `mojeek` HTML backends | Not carried over. |
| Matching the URL text against private ranges | Bypassed by DNS and redirects; addresses are checked after resolution and on every hop. |
| Optional extensions (`evo-websearch`, `evo-webfetch`) | The desktop installed neither; a built-in tool reaches every chat. |

## 5. As-built notes

- **Layer 1** lives in its own crate `evo-web` plus
  `crates/evo-engine/src/web_tools.rs`, not in `evo-tools`. The designed
  `raw` input (skip extraction) is not built; PDFs are refused rather than
  turned into text; the wrapper carries `url` and `title`, not `fetched_at`.
  The designed per-domain Allow / Ask / Block permission is not built: both
  tools run without approval (FR-10 stays proposed). The designed "pin the
  checked address" is done by making the guard the HTTP client's DNS
  resolver: the check runs at connection time on every address, so DNS
  rebinding cannot reach a private address.
- **Layer 2** is a keyless chain (DuckDuckGo, then Exa, then Wikipedia), as
  evo v3 did, instead of keyed backends; keyed backends and **Settings → Web**
  are not built.
- **Layer 3** is not built.
- Checked with a real model (2026-11-06): it searched, read the official
  page, and answered with the source URL.
