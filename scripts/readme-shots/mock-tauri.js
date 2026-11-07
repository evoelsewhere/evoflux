// README screenshots only (capture_app.py): a fake Tauri IPC and a fake engine
// that replays a canned chat. Injected before the app loads; not app code.
// Handlers return what the shell's commands return; anything unknown gets
// `null` and is listed in `window.__mockUnknown`.
(() => {
  const T0 = Date.now() - 6 * 60_000;
  const at = (s) => T0 + s * 1000;
  const HOME = "C:\\Users\\demo";
  const WS = [
    { id: "ws-evo", path: "C:\\Users\\demo\\code\\evo-harness", name: "evo-harness", collapsed: false, position: 0, createdAt: T0, openedAt: T0 },
    { id: "ws-site", path: "C:\\Users\\demo\\code\\website", name: "website", collapsed: false, position: 1, createdAt: T0, openedAt: T0 },
  ];
  const chat = (id, workspaceId, title, minutesAgo, extra = {}) => ({
    id, workspaceId, title, titleSource: "auto", preview: null, provider: "openai", model: "gpt-5.1",
    pinned: false, unread: false, archivedAt: null, turnCount: 1, costUsd: 0.04, tokens: 18000,
    createdAt: Date.now() - minutesAgo * 60_000, updatedAt: Date.now() - minutesAgo * 60_000,
    parentChatId: null, origin: "user", worktreePath: null, ...extra,
  });
  const CHATS = [
    chat("c1", "ws-evo", "Retry web_fetch on 429 and 503", 1),
    chat("c2", "ws-evo", "Explain the session mesh hub", 42),
    chat("c3", "ws-evo", "Review the LSP installer change", 180, { unread: true }),
    chat("c4", "ws-evo", "Speed up transcript search", 1500),
    chat("c5", "ws-site", "Write the 4.0 release notes", 95, { pinned: true }),
    chat("c6", "ws-site", "Fix the pricing page layout", 2900),
    chat("c7", null, "Plan the week", 3000),
  ];

  const FETCH_BEFORE = [
    "pub async fn fetch_page(client: &Client, url: &Url) -> Result<Page> {",
    "    check_public(url)?;",
    "    let response = client.get(url.clone()).send().await?;",
    "    if !response.status().is_success() {",
    "        return Err(FetchError::Status(response.status()));",
    "    }",
    "    Page::from_response(response).await",
    "}",
  ].join("\n");

  const DIFF = [
    " 86     check_public(url)?;",
    "-87     let response = client.get(url.clone()).send().await?;",
    "+87     let response = send_with_retry(client, url, RetryPolicy::default()).await?;",
    " 88     if !response.status().is_success() {",
    " ...",
    "+104 /// Retries 429 and 503 up to three times, waiting `Retry-After` or 1 s, 2 s, 4 s.",
    "+105 async fn send_with_retry(client: &Client, url: &Url, policy: RetryPolicy) -> Result<Response> {",
    "+106     let mut attempt = 0;",
    "+107     loop {",
    "+108         let response = client.get(url.clone()).send().await?;",
    "+109         if !policy.should_retry(response.status(), attempt) {",
    "+110             return Ok(response);",
    "+111         }",
    "+112         tokio::time::sleep(policy.delay(&response, attempt)).await;",
    "+113         attempt += 1;",
    "+114     }",
    "+115 }",
  ].join("\n");

  const TEST_OUT = [
    "   Compiling evo-web v0.1.0 (crates/evo-web)",
    "    Finished `test` profile [unoptimized + debuginfo] target(s) in 6.84s",
    "     Running unittests src/lib.rs",
    "",
    "running 5 tests",
    "test fetch::tests::retries_429_then_succeeds ... ok",
    "test fetch::tests::honours_retry_after_seconds ... ok",
    "test fetch::tests::gives_up_after_three_tries ... ok",
    "test fetch::tests::does_not_retry_404 ... ok",
    "test fetch::tests::rejects_private_addresses ... ok",
    "",
    "test result: ok. 5 passed; 0 failed; 0 ignored; finished in 0.21s",
  ].join("\n");

  const usage = (input, output) => ({ input, output, cacheRead: Math.round(input * 0.6), cacheWrite: 0, totalTokens: input + output, cost: { input: 0.002, output: 0.004, cacheRead: 0.0004, cacheWrite: 0, total: 0.0064 } });
  const assistant = (s, content, extra = {}) => ({ role: "assistant", content, provider: "openai", model: "gpt-5.1", api: "openai-responses", stopReason: "toolUse", usage: usage(9000, 300), timestamp: at(s), ...extra });
  const result = (s, id, name, text, extra = {}) => ({ role: "toolResult", toolCallId: id, toolName: name, content: [{ type: "text", text }], isError: false, timestamp: at(s), ...extra });

  const MESSAGES = [
    { role: "user", content: [{ type: "text", text: "web_fetch gives up on the first 429. Add a retry with backoff (three tries, honour Retry-After) and cover it with tests." }], timestamp: at(0) },
    assistant(4, [
      { type: "thinking", thinking: "Find where web_fetch sends the request, then wrap that call so 429 and 503 retry with Retry-After or exponential backoff. Keep the public-address check before every attempt." },
      { type: "text", text: "I'll find where `web_fetch` sends its request." },
      { type: "toolCall", id: "t1", name: "grep", arguments: { pattern: "fn fetch_page", path: "crates/evo-web" } },
    ]),
    result(5, "t1", "grep", "crates/evo-web/src/fetch.rs:84:pub async fn fetch_page(client: &Client, url: &Url) -> Result<Page> {"),
    assistant(8, [{ type: "toolCall", id: "t2", name: "read", arguments: { path: "crates/evo-web/src/fetch.rs", offset: 84, limit: 8 } }]),
    result(9, "t2", "read", FETCH_BEFORE),
    assistant(21, [
      { type: "text", text: "One request, no retry. I'll route it through a small retry helper." },
      { type: "toolCall", id: "t3", name: "edit", arguments: { path: "crates/evo-web/src/fetch.rs", oldText: "let response = client.get(url.clone()).send().await?;", newText: "let response = send_with_retry(client, url, RetryPolicy::default()).await?;" } },
    ]),
    result(22, "t3", "edit", "Successfully replaced text in crates/evo-web/src/fetch.rs.", { details: { diff: DIFF, firstChangedLine: 87 } }),
    assistant(30, [{ type: "toolCall", id: "t4", name: "bash", arguments: { command: "cargo test -p evo-web fetch" } }]),
    result(38, "t4", "bash", TEST_OUT),
    assistant(44, [
      { type: "text", text: [
        "`web_fetch` now retries rate-limited and unavailable pages instead of failing on the first answer.",
        "",
        "- **`send_with_retry`** in `crates/evo-web/src/fetch.rs` retries **429** and **503** up to three times.",
        "- It waits for `Retry-After` when the site sends one, otherwise 1 s, 2 s and 4 s.",
        "- The public-address check still runs before the first request, so redirects stay safe.",
        "",
        "Four new tests cover the retry, `Retry-After`, giving up after three tries and not retrying a 404. All 5 tests in `evo-web` pass.",
      ].join("\n") },
    ], { stopReason: "stop", usage: usage(12400, 420) }),
  ];

  const MODELS = [
    { id: "gpt-5.1", name: "GPT-5.1", api: "openai-responses", provider: "openai", reasoning: true, contextWindow: 400000, maxTokens: 128000 },
    { id: "gemini-3-pro", name: "Gemini 3 Pro", api: "google", provider: "google", reasoning: true, contextWindow: 1000000, maxTokens: 64000 },
    { id: "qwen3-coder", name: "Qwen3 Coder", api: "openai-completions", provider: "ollama", reasoning: false, contextWindow: 256000, maxTokens: 32000 },
  ];
  const STATE = { modelId: "gpt-5.1", model: "GPT-5.1", provider: "openai", thinkingLevel: "medium", context: { tokens: 31200, window: 400000, percent: 7.8 } };

  // ── IPC plumbing (same contract as @tauri-apps/api/mocks) ──────────────
  const callbacks = new Map();
  const listeners = new Map();
  let nextCb = 1;
  const run = (id, data) => { const cb = callbacks.get(id); if (cb) cb(data); };
  const emit = (event, payload) => {
    for (const handler of listeners.get(event) || []) run(handler, { event, id: handler, payload });
  };
  window.__mockEmit = emit;

  const engineReply = (chat, message) => {
    if (message.type === "mesh") {
      return { type: "mesh", v: message.v, id: "r" + message.id, kind: "res", corr: message.id, op: message.op, from: "hub", to: message.from, seq: 0, ts: Date.now(), body: message.op === "list" ? { nodes: [] } : {} };
    }
    const data = (() => {
      switch (message.type) {
        case "get_messages": return { messages: chat === "c1" ? MESSAGES : [] };
        case "get_state": return STATE;
        case "get_available_models": return { models: MODELS };
        case "get_available_thinking_levels": return { levels: ["off", "low", "medium", "high"] };
        case "get_default_model": return { provider: "openai", modelId: "gpt-5.1" };
        case "list_language_servers": return { servers: [], suggestions: [] };
        case "get_context_breakdown": return { window: 400000, total: 31200, percent: 7.8, estimated: false, compactionEnabled: true, untilCompact: 340000, categories: [], tools: [], skills: [], contextFiles: [] };
        default: return {};
      }
    })();
    return { type: "response", id: message.id, command: message.type, success: true, data };
  };

  const handlers = {
    "plugin:event|listen": ({ event, handler }) => { if (!listeners.has(event)) listeners.set(event, []); listeners.get(event).push(handler); return handler; },
    "plugin:event|unlisten": () => null,
    "plugin:event|emit": ({ event, payload }) => { emit(event, payload); return null; },
    "plugin:event|emit_to": ({ event, payload }) => { emit(event, payload); return null; },
    "plugin:path|resolve_directory": () => HOME,
    "plugin:app|version": () => "4.0.0",
    "plugin:app|name": () => "Evo Harness",
    "plugin:window|is_maximized": () => false,
    "plugin:window|is_fullscreen": () => false,
    "plugin:window|is_focused": () => true,
    "plugin:window|scale_factor": () => 1,
    "window_material": () => "none",
    "settings_all": () => ({ "ui.lastChat": "c1" }),
    "workspaces_list": () => WS,
    "chats_list": ({ archived }) => (archived ? [] : CHATS),
    "chats_search": () => [],
    "engine_info": () => ({ binary: "evo-engine", exists: true, extra_args: [] }),
    "engine_running": () => [],
    "engine_start": ({ chat }) => { setTimeout(() => emit("engine://message", { chat, generation: 1, message: { type: "ready" } }), 30); return 1; },
    "engine_send": ({ chat, message }) => { setTimeout(() => emit("engine://message", { chat, generation: 1, message: engineReply(chat, message) }), 10); return null; },
    "engine_stop": () => null,
    "mesh_pending_chats": () => [],
    "mesh_session_tools": () => [],
    "mcp_chat_tools": () => [],
    "terminal_shells": () => [],
    "terminal_list": () => [],
    "open_apps": () => [],
    "browser_list": () => [],
    "worktree_list": () => [],
    "logs_query": () => [],
    "system_settings": () => ({}),
  };

  window.__mockHandlers = handlers;
  window.__mockUnknown = new Set();
  async function invoke(cmd, args = {}) {
    const handler = handlers[cmd];
    if (handler) return handler(args);
    window.__mockUnknown.add(cmd);
    return null;
  }

  window.isTauri = true;
  window.__TAURI_INTERNALS__ = {
    invoke,
    transformCallback(callback, once = false) {
      const id = nextCb++;
      callbacks.set(id, (data) => { if (once) callbacks.delete(id); return callback && callback(data); });
      return id;
    },
    unregisterCallback(id) { callbacks.delete(id); },
    runCallback: run,
    callbacks,
    convertFileSrc: (path) => path,
    metadata: { currentWindow: { label: "main" }, currentWebview: { windowLabel: "main", label: "main" } },
    plugins: { path: { sep: "\\", delimiter: ";" } },
  };
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener(_event, id) { callbacks.delete(id); } };
})();
