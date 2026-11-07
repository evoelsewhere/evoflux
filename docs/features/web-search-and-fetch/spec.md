# Web search and web fetch — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-web` · engine · desktop UI |
| Created | 2026-11-06 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Agent tools](../agent-tools/spec.md) |

## 1. Summary

The agent can search the web and read public pages in every chat, with any
model and without a key or account. `web_search` returns a short list of
results from free search services, falling back from one to the next when a
service is blocked or empty; `web_fetch` reads one public page as Markdown.
Pages are untrusted data, never instructions, and only public addresses are
reachable. Keyed search services, per-domain fetch permissions and the model
provider's own search are proposed, not built.

## 2. Scope

### 2.1 Goals

- Give every chat a built-in way to find current information and read
  documentation, errors and other public pages, with no setup.
- Keep fetching safe: public addresses only, bounded time and size, no
  cookies or credentials, pages treated as untrusted data.
- Use free search services honestly and at low volume, and say clearly when
  none of them answers.
- Show searches and reads in the transcript in a readable form.
- Later (proposed): keyed search services, per-domain fetch permissions, the
  model provider's own search with citations.

### 2.2 Non-goals

- Pages that need JavaScript, a login or clicking: the in-app browser tools
  (`browser_*`, a real browser the agent drives) stay the tool for those.
- Reading PDFs and other binary files from the web: `web_fetch` points to the
  browser instead.
- Summarising long pages with a second model (decided against for now, see
  6.2).

## 3. User scenarios

### US-1 Answer from the web with a source (priority P1)

A person asks about something not in the project or the model's knowledge
(current documentation, a recent release, an error message).

Acceptance scenarios:

1. **Given** a chat with web tools on, **when** the person asks a question
   that needs the web, **then** the agent searches, reads the official page
   and answers with the source URL.

### US-2 Read a page the person names (priority P1)

A person pastes a link and asks about it.

Acceptance scenarios:

1. **Given** a public HTML page, **when** the agent calls `web_fetch`,
   **then** it gets the main content as Markdown without menus, scripts or
   forms, and a long page comes in parts it can continue with `offset`.
2. **Given** a link to a private-network address, **when** the agent calls
   `web_fetch`, **then** the call fails before any request is sent.

### US-3 Search while a service is blocked (priority P2)

The first search service answers with a block page.

Acceptance scenarios:

1. **Given** the first service is blocked, **when** the agent searches,
   **then** the next service answers and the result says which one did.
2. **Given** every service fails, **then** the tool says so and lists each
   failure.

### US-4 Turn web tools off (priority P3)

A person does not want chats to reach the web through these tools.

Acceptance scenarios:

1. **Given** `webTools: false` in settings, **then** neither tool is offered
   to the model.

### Edge cases

- A company proxy answers with its own block page: `web_fetch` returns it as
  an HTTP error.
- A PDF or other binary: refused with a pointer to the browser.
- A page with no readable text: the result says the page may need JavaScript
  and points to the browser tools.
- A page over the size cap: only the start is read, and the result says so.
- An `offset` past the end of the page: refused.
- Queries are sent as typed to the search services (third parties); secrets
  in a query are not redacted.

## 4. Requirements

The tool schemas below are a contract the model sees.

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | `web_fetch {url, offset?}` reads a public http(s) page, following at most 5 redirects. HTML becomes the main content (the article, main region or body, without navigation, scripts, forms and images; links absolute; empty links dropped) as Markdown; text, JSON and XML come as they are, with the charset from the header or `<meta>`. Output is 40,000 characters per call, with a line saying which `offset` continues. PDFs and other binaries are refused with a pointer to the browser; pages that need JavaScript or a login are pointed to the browser tools. | Given an article page, then the result is its main text as Markdown; given a long page, then the result ends with the next `offset`. |
| FR-2 | `web_fetch` reaches public addresses only. Every address a host resolves to is checked, on every redirect hop: private, loopback, link-local, CGNAT, multicast, documentation and metadata addresses are refused (IPv4-mapped, NAT64 and 6to4 forms unwrapped first); IP literals, schemes, credentials in the URL and `localhost` are checked too. | Given a URL to a private or loopback address, then the call fails before any request. |
| FR-3 | The fetched page is wrapped as a web page with its URL and title and described to the model as data, never instructions. | The tool result starts with the page wrapper and the tool description says not to follow instructions in it. |
| FR-4 | `web_search {query, max_results?, allowed_domains?, blocked_domains?, recency?}` (`max_results` 1–20, default 8; `recency` day, week, month or year) returns numbered results — title, URL, snippet, date — with snippets cut at 3,000 characters, and tells the model to read a result before relying on it and to cite the URLs it uses. | Given a query, then numbered results with title, URL and snippet come back. |
| FR-5 | `web_search` needs no key: it tries free search services in order (DuckDuckGo's page for browsers without JavaScript, then Exa's hosted search, then English Wikipedia). The first with results after the domain filter answers; a failed or paused service is skipped; the error lists every service's failure only when all fail. The result says which service answered. Wikipedia is skipped when the query has a period or domain limits other than Wikipedia. | Given a blocked first service, then the next answers; given domain limits, then results outside them are dropped. |
| FR-6 | Repeated calls are cached: a fetched page for 15 minutes per URL; a search for 10 minutes, keyed on the normalised query, limits and result count. | Given the same search twice within 10 minutes, then the second makes no request. |
| FR-7 | `webTools: false` in settings leaves both tools out. Both run without an approval prompt, like `read`. | Given `webTools: false`, then the model is not offered either tool. |
| FR-8 | The transcript shows a search as "Searched the web · query" with the results as links that open in the browser, and a read as "Read · host/path" with the page text. | Manual check in the running app. |
| FR-9 | *(Proposed.)* Keyed search services (Brave, Tavily, Exa, Serper, a SearXNG URL) can be chosen in **Settings → Web**, with the key stored with the other credentials and applied without a restart, and a **Test** button. | Given a configured key, when the agent searches, then the chosen service answers. |
| FR-10 | *(Proposed.)* `web_fetch` asks per domain: Allow / Ask / Block, default Ask for a domain not seen before in the chat, with **Always allow this domain** saved in settings; **Settings → Web** lists the domains. | Given a new domain, when the agent fetches it, then the person is asked first. |
| FR-11 | *(Proposed.)* When the chosen model supports the provider's own web search and **Use the model's own search** is on, the provider's search is used instead of (or beside) `web_search`; its results keep working across turns, its citations show in the transcript, and its cost shows in the turn's usage. | Given a model with provider search and the setting on, then a search turn shows provider citations and the search cost. |
| FR-12 | *(Proposed.)* The search result list shows a favicon, domain and title per result, and citations show as numbered chips linking to their sources. | Manual check in the running app. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Fetches are bounded: 20 s timeout, 5 MB body (a larger page is cut and the result says so), no cookies, no proxy. | A slow or huge page ends within the limits. |
| NFR-2 | Both tools work with every model and need no key, account or server. | A fresh install with any model can search and fetch. |
| NFR-3 | Free services are used honestly and at low volume: evo's own user agent (no browser impersonation), at least 1.5 s between DuckDuckGo requests, a block page pauses DuckDuckGo for 90 s (searches queued behind it skip it without sending a request), and a rate-limit answer pauses Exa for 60 s. | Given a block page, then the next searches skip that service until the pause ends. |

## 5. Success criteria

- SC-1 A question about a public fact is answered with a cited source URL,
  with nothing configured.
- SC-2 No fetch ever reaches a private-network or metadata address.
- SC-3 When one search service is blocked, a search still answers whenever
  another service has results.

## 6. Clarifications

### 6.1 Open

None.

### 6.2 Resolved

- 2026-11-07 — Q: Which search service is the default, and should a keyless
  service (a SearXNG instance) be bundled? → A: The keyless chain stays the
  default; keyed services are an option in **Settings → Web** (FR-9).
- 2026-11-07 — Q: Should `web_fetch` optionally summarise a long page with a small
  model? → A: Not for now; `offset` paging covers long pages (section 2.2).
- 2026-11-07 — Q: Per chat, per project or global domain permissions? → A: Ask per
  chat for a domain not seen before in the chat; **Always allow this
  domain** saves it in settings (FR-10).

## 7. History

- 2026-11-06 — Proposal written: built-in `web_fetch`, then `web_search`
  with a choice of service, then the provider's own search.
- 2026-11-06 — `web_fetch` and `web_search` built; search uses a keyless
  chain (DuckDuckGo, then Exa, then Wikipedia) instead of keyed services.
- 2026-11-07 — Moved to the spec / plan / tasks format.
- 2026-11-07 — Open clarifications answered by the owner (accepted as proposed).
