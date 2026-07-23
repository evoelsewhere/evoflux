"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const workerSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "background.js"),
  "utf8"
);
const teachRecorderSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "teach_recorder.js"),
  "utf8"
);
const popupSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "popup.js"),
  "utf8"
);
const markdownSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "markdown.js"),
  "utf8"
);
const sidePanelSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "sidepanel.js"),
  "utf8"
);
const sidePanelHtml = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "sidepanel.html"),
  "utf8"
);
const extensionManifest = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "manifest.json"),
  "utf8"
));

function eventChannel() {
  const listeners = new Set();
  return {
    addListener(listener) {
      listeners.add(listener);
    },
    removeListener(listener) {
      listeners.delete(listener);
    },
    emit(...args) {
      for (const listener of listeners) listener(...args);
    },
  };
}

function loadWorker(options = {}) {
  const cdpCalls = [];
  const detachedTabs = [];
  const fetchCalls = [];
  const sockets = [];
  const menuItems = [];
  const actionCalls = [];
  const scriptCalls = [];
  const alarmCalls = [];
  const tabMessages = [];
  const sidePanelCalls = [];
  const tabGroupCalls = [];
  const storedConfig = {
    extensionId: "ext-test",
    ...(options.storedConfig || {}),
  };
  const storedSession = { ...(options.storedSession || {}) };
  let cdpResponder = () => ({});
  const tabList = [
    {
      id: 1,
      windowId: 10,
      active: true,
      pinned: false,
      title: "Active",
      url: "https://example.com/active",
    },
    {
      id: 2,
      windowId: 10,
      active: false,
      pinned: true,
      title: "Loading",
      url: "",
      pendingUrl: "https://example.com/pending",
    },
  ];

  const runtime = {
    lastError: null,
    getManifest: () => ({ version: "test" }),
    onStartup: eventChannel(),
    onInstalled: eventChannel(),
    onMessage: eventChannel(),
    async sendMessage(message) {
      runtime.onMessage.emit(message, null, () => {});
      return { ok: true };
    },
  };
  let scriptResponder = options.scriptResponder || (() => [{ result: false }]);
  const tabs = {
    onRemoved: eventChannel(),
    onUpdated: eventChannel(),
    onActivated: eventChannel(),
    onCreated: eventChannel(),
    onMoved: eventChannel(),
    async query(queryInfo = {}) {
      if (queryInfo.active) return tabList.filter((tab) => tab.active);
      if (queryInfo.groupId != null) return tabList.filter((tab) => tab.groupId === queryInfo.groupId);
      if (queryInfo.windowId != null) return tabList.filter((tab) => tab.windowId === queryInfo.windowId);
      return tabList;
    },
    async get(tabId) {
      const tab = tabList.find((candidate) => candidate.id === tabId);
      if (!tab) throw new Error(`No tab ${tabId}`);
      return tab;
    },
    async update(tabId, changes) {
      const tab = await this.get(tabId);
      if (changes.active) {
        for (const candidate of tabList) {
          if (candidate.windowId === tab.windowId) candidate.active = false;
        }
      }
      Object.assign(tab, changes);
      return tab;
    },
    async create(options) {
      const tab = {
        id: Math.max(...tabList.map((candidate) => candidate.id)) + 1,
        windowId: options.windowId ?? 10,
        active: options.active ?? true,
        pinned: false,
        title: "",
        url: options.url,
        groupId: -1,
        openerTabId: options.openerTabId,
        index: options.index,
      };
      tabList.push(tab);
      return tab;
    },
    async group(options) {
      tabGroupCalls.push({ kind: "group", options });
      const groupId = options.groupId ?? 77;
      const tabIds = Array.isArray(options.tabIds) ? options.tabIds : [options.tabIds];
      for (const tabId of tabIds) {
        const tab = tabList.find((candidate) => candidate.id === tabId);
        if (tab) tab.groupId = groupId;
      }
      return groupId;
    },
    async remove(tabId) {
      const index = tabList.findIndex((tab) => tab.id === tabId);
      if (index >= 0) tabList.splice(index, 1);
    },
    async sendMessage(tabId, message) {
      tabMessages.push({ tabId, message });
      if (options.tabMessageResponder) {
        return options.tabMessageResponder(tabId, message);
      }
      return { ok: true };
    },
    async goBack() {},
    async goForward() {},
    async reload() {},
  };
  const chrome = {
    runtime,
    storage: {
      local: {
        async get() {
          return { ...storedConfig };
        },
        async set(values) {
          Object.assign(storedConfig, values);
        },
        async remove(keys) {
          for (const key of keys) delete storedConfig[key];
        },
      },
      session: {
        async get() {
          return { ...storedSession };
        },
        async set(values) {
          Object.assign(storedSession, values);
        },
        async remove(keys) {
          for (const key of keys) delete storedSession[key];
        },
      },
    },
    alarms: {
      create(name, alarmInfo) {
        alarmCalls.push({ name, alarmInfo });
      },
      onAlarm: eventChannel(),
    },
    contextMenus: {
      onClicked: eventChannel(),
      removeAll(callback) {
        menuItems.length = 0;
        callback?.();
      },
      create(item, callback) {
        menuItems.push(item);
        callback?.();
        return item.id;
      },
    },
    action: {
      setBadgeText(options) { actionCalls.push({ kind: "badge", options }); },
      setBadgeBackgroundColor(options) { actionCalls.push({ kind: "color", options }); },
      setTitle(options) { actionCalls.push({ kind: "title", options }); },
    },
    scripting: {
      async executeScript(options) {
        scriptCalls.push(options);
        return scriptResponder(options);
      },
    },
    sidePanel: {
      async open(options) {
        sidePanelCalls.push({ kind: "open", options });
      },
      async setPanelBehavior(options) {
        sidePanelCalls.push({ kind: "behavior", options });
      },
    },
    tabGroups: {
      async update(groupId, options) {
        tabGroupCalls.push({ kind: "update", groupId, options });
        return { id: groupId, ...options };
      },
    },
    tabs,
    windows: { async update() {} },
    debugger: {
      onEvent: eventChannel(),
      onDetach: eventChannel(),
      attach(_target, _version, callback) {
        runtime.lastError = null;
        callback();
      },
      detach({ tabId }, callback) {
        detachedTabs.push(tabId);
        runtime.lastError = null;
        callback();
      },
      sendCommand({ tabId }, method, params, callback) {
        cdpCalls.push({ tabId, method, params });
        runtime.lastError = null;
        callback(cdpResponder(method, params));
      },
    },
  };

  class FakeWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 3;

    constructor(url) {
      this.url = url;
      this.readyState = FakeWebSocket.CONNECTING;
      this.sent = [];
      sockets.push(this);
    }

    send(message) {
      this.sent.push(message);
    }

    close() {
      this.readyState = FakeWebSocket.CLOSED;
      if (this.onclose) this.onclose({ code: 1000 });
    }
  }

  const context = vm.createContext({
    chrome,
    console: { log() {}, warn() {}, error() {} },
    async fetch(url, init = {}) {
      fetchCalls.push({ url, init });
      if (options.fetchResponder) return options.fetchResponder(url, init);
      throw new Error("Unexpected fetch");
    },
    navigator: { userAgent: "Chrome/140" },
    URL,
    WebSocket: FakeWebSocket,
    clearTimeout,
    setTimeout,
  });
  vm.runInContext(workerSource, context, { filename: "background.js" });

  return {
    cdpCalls,
    context,
    detachedTabs,
    fetchCalls,
    menuItems,
    actionCalls,
    alarmCalls,
    scriptCalls,
    tabMessages,
    sidePanelCalls,
    tabGroupCalls,
    sockets,
    storedConfig,
    storedSession,
    setTabUrl(tabId, url) {
      const tab = tabList.find((candidate) => candidate.id === tabId);
      if (!tab) throw new Error(`No tab ${tabId}`);
      tab.url = url;
      tab.pendingUrl = "";
    },
    run(expression) {
      return vm.runInContext(expression, context);
    },
    setCdpResponder(responder) {
      cdpResponder = responder;
    },
    setScriptResponder(responder) {
      scriptResponder = responder;
    },
  };
}

function loadTeachRecorder() {
  const listeners = {};
  const sent = [];
  const runtimeMessages = eventChannel();

  class FakeElement {
    constructor(attributes = {}) {
      this.attributes = attributes;
      this.tagName = attributes.tagName || "INPUT";
      this.id = attributes.id || "";
      this.parentElement = null;
    }
    getAttribute(name) {
      return this.attributes[name] ?? null;
    }
    closest() {
      return this;
    }
  }
  class FakeInput extends FakeElement {
    constructor(attributes = {}) {
      super({ ...attributes, tagName: "INPUT" });
      this.type = attributes.type || "text";
      this.name = attributes.name || "";
      this.autocomplete = attributes.autocomplete || "";
      this.placeholder = attributes.placeholder || "";
      this.value = attributes.value || "";
      this.checked = Boolean(attributes.checked);
    }
  }
  class FakeTextArea extends FakeElement {
    constructor(attributes = {}) {
      super({ ...attributes, tagName: "TEXTAREA" });
      this.name = attributes.name || "";
      this.autocomplete = attributes.autocomplete || "";
      this.placeholder = attributes.placeholder || "";
      this.value = attributes.value || "";
    }
  }
  class FakeSelect extends FakeElement {}

  const context = vm.createContext({
    chrome: {
      runtime: {
        onMessage: runtimeMessages,
        async sendMessage(message) {
          sent.push(message);
          return { ok: true };
        },
      },
    },
    document: {
      addEventListener(type, listener) {
        listeners[type] = listener;
      },
    },
    Element: FakeElement,
    HTMLInputElement: FakeInput,
    HTMLTextAreaElement: FakeTextArea,
    HTMLSelectElement: FakeSelect,
    CSS: { escape: (value) => String(value) },
    console: { log() {}, warn() {}, error() {} },
  });
  vm.runInContext(teachRecorderSource, context, { filename: "teach_recorder.js" });
  runtimeMessages.emit({ type: "webbridge_teach_recording", enabled: true }, null, () => {});
  return { context, listeners, sent, FakeInput, FakeTextArea };
}

test("P2 popup opens the Side Panel directly inside the click gesture", () => {
  const start = popupSource.indexOf("function openSidePanel()");
  const end = popupSource.indexOf("// ── Wiring", start);
  assert.ok(start >= 0 && end > start);
  const implementation = popupSource.slice(start, end);

  assert.match(implementation, /chrome\.sidePanel\.open\(options\)/);
  assert.doesNotMatch(implementation, /chrome\.runtime\.sendMessage\s*\(/);
  assert.match(
    popupSource,
    /openSidePanelBtn\.addEventListener\("click", openSidePanel\)/,
  );
});

test("P2 Side Chat auto-creates and binds one session for an unbound tab", async () => {
  let sessionCreates = 0;
  let bindingCreates = 0;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/sessions") && !init.method) {
        return { ok: true, async json() { return [{ id: "session-auto", title: "Browser: Active" }]; } };
      }
      if (url.endsWith("/bindings") && !init.method) {
        return { ok: true, async json() { return []; } };
      }
      if (url.endsWith("/sessions") && init.method === "POST") {
        sessionCreates += 1;
        return { ok: true, async json() { return { id: "session-auto", title: "Browser: Active" }; } };
      }
      if (url.endsWith("/bindings/1") && init.method === "PUT") {
        bindingCreates += 1;
        return { ok: true, async json() { return { tab_id: 1, session_id: "session-auto" }; } };
      }
      throw new Error(`Unexpected fetch ${url} ${init.method || "GET"}`);
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  const response = await worker.run(`new Promise((resolve) => {
    chrome.runtime.onMessage.emit(
      { type: "ensure_browser_session_for_tab", action_id: "auto-bind-1" },
      null,
      resolve
    );
  })`);

  assert.equal(response.ok, true);
  assert.equal(response.session_id, "session-auto");
  assert.equal(response.tab.id, 1);
  assert.equal(sessionCreates, 1);
  assert.equal(bindingCreates, 1);
});

test("P2 extension action opens Side Chat and settings live inside the panel", () => {
  assert.equal(extensionManifest.action.default_popup, undefined);
  assert.equal(extensionManifest.content_scripts, undefined);
  assert.equal(extensionManifest.web_accessible_resources, undefined);
  assert.ok(extensionManifest.permissions.includes("tabGroups"));
  assert.match(workerSource, /openPanelOnActionClick: true/);
  assert.match(sidePanelHtml, /id="settingsDrawer"/);
  assert.match(sidePanelHtml, /id="relayBaseInput"/);
  assert.match(sidePanelHtml, /id="pairLocalBtn"/);
  assert.doesNotMatch(sidePanelHtml, /id="sessionSelect"/);
  assert.doesNotMatch(sidePanelHtml, /id="bindBtn"/);
  assert.doesNotMatch(sidePanelHtml, /Legacy access token|accessTokenInput/);
  assert.doesNotMatch(popupSource, /accessTokenInput|Legacy connection/);
  assert.doesNotMatch(workerSource, /[?&]_token=/);
});

test("P2 Side Chat strips extension-only tab metadata from picked elements", () => {
  const start = sidePanelSource.indexOf("function browserPanelElement(");
  const end = sidePanelSource.indexOf("\n}\n", start) + 3;
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({ result: null });
  vm.runInContext(`${sidePanelSource.slice(start, end)}
    result = browserPanelElement({
      tab_id: 874320141,
      page_url: "https://example.com/page",
      selector: "#save",
      tag: "button",
      role: "button",
      name: "Save",
      text: "Save",
      internal: "must-not-leak"
    }, 874320141);`, context);

  assert.equal(context.result.page_url, "https://example.com/page");
  assert.equal(context.result.selector, "#save");
  assert.equal("tab_id" in context.result, false);
  assert.equal("internal" in context.result, false);
});

test("P2 a session opens child tabs in a named Chrome tab group", async () => {
  let sessionCreates = 0;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/bindings")) {
        return {
          ok: true,
          async json() {
            return [{
              tab_id: 1,
              session_id: "session-123456",
              origin: "https://example.com",
            }];
          },
        };
      }
      if (url.endsWith("/sessions") && !init.method) {
        return {
          ok: true,
          async json() { return [{ id: "session-123456", title: "Browser: Active" }]; },
        };
      }
      if (url.endsWith("/sessions") && init.method === "POST") {
        sessionCreates += 1;
      }
      throw new Error(`Unexpected fetch ${url}`);
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  const response = await worker.run(`new Promise((resolve) => {
    chrome.runtime.onMessage.emit(
      { type: "open_grouped_session_tab", session_id: "session-123456" },
      null,
      resolve
    );
  })`);

  assert.equal(response.ok, true);
  assert.equal(response.tab_id, 3);
  assert.equal(response.group_id, 77);
  assert.equal(worker.tabGroupCalls[0].options.tabIds[0], 1);
  assert.equal(worker.tabGroupCalls[0].options.tabIds[1], 3);
  assert.equal(worker.tabGroupCalls[1].kind, "update");
  assert.equal(worker.tabGroupCalls[1].options.title, "EvoFlux · Active");
  const child = await worker.run("chrome.tabs.get(3)");
  assert.equal(child.openerTabId, 1);
  assert.equal(child.windowId, 10);
  assert.equal(child.active, false);

  await worker.run("chrome.tabs.update(3, { active: true })");
  worker.setTabUrl(3, "https://child.example/work");
  const childContext = await worker.run(`new Promise((resolve) => {
    chrome.runtime.onMessage.emit(
      { type: "ensure_browser_session_for_tab", action_id: "child-resolve" },
      null,
      resolve
    );
  })`);
  assert.equal(childContext.ok, true);
  assert.equal(childContext.session_id, "session-123456");
  assert.equal(childContext.binding_tab_id, 1);
  assert.equal(childContext.grouped, true);
  assert.equal(sessionCreates, 0);
});

test("P2 parallel subagents join one session tab group", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));

  const results = await worker.run(`Promise.all([
    createGroupedSessionTab(
      { id: 1, windowId: 10, groupId: -1, title: "Primary" },
      "lead-session",
      { url: "https://one.example", active: false }
    ),
    createGroupedSessionTab(
      { id: 1, windowId: 10, groupId: -1, title: "Primary" },
      "lead-session",
      { url: "https://two.example", active: false }
    )
  ])`);

  assert.equal(results[0].group_id, 77);
  assert.equal(results[1].group_id, 77);
  assert.equal((await worker.run("chrome.tabs.get(1)")).groupId, 77);
  assert.equal((await worker.run("chrome.tabs.get(3)")).groupId, 77);
  assert.equal((await worker.run("chrome.tabs.get(4)")).groupId, 77);
  const createGroupCalls = worker.tabGroupCalls.filter((call) => (
    call.kind === "group" && call.options.createProperties
  ));
  assert.equal(createGroupCalls.length, 1);
});

test("P2 Side Chat supports persisted light and dark themes", () => {
  assert.match(sidePanelHtml, /:root\[data-theme="light"\]/);
  assert.match(sidePanelHtml, /data-theme-value="system"/);
  assert.match(sidePanelHtml, /data-theme-value="light"/);
  assert.match(sidePanelHtml, /data-theme-value="dark"/);
  assert.match(sidePanelSource, /webbridgeSideChatTheme/);
  assert.match(sidePanelSource, /dataset\.theme = themePreference/);
  assert.match(sidePanelSource, /delete document\.documentElement\.dataset\.theme/);
  assert.match(sidePanelSource, /THEME_STORAGE_KEY]: themePreference/);
});

test("P2 Side Chat renders progressive activity and throttles Markdown", () => {
  assert.match(sidePanelHtml, /id="activity"/);
  assert.match(sidePanelSource, /type === "agent_status"/);
  assert.match(sidePanelSource, /type === "activity"/);
  assert.match(sidePanelSource, /LOADING_VERBS/);
  assert.match(sidePanelSource, /}, 80\)/);
  assert.match(sidePanelSource, /transcriptPinned/);
});

test("P2 composer exposes model selection and icon-only browser controls", () => {
  assert.match(sidePanelHtml, /id="modelTrigger"/);
  assert.match(sidePanelHtml, /id="modelSearch"/);
  assert.match(sidePanelHtml, /id="modelList"/);
  assert.match(sidePanelSource, /\/api\/team\/webbridge\/models/);
  assert.match(sidePanelSource, /\/model`/);
  for (const id of ["pickElementBtn", "takeControlBtn", "resumeAgentBtn", "sendBtn"]) {
    const start = sidePanelHtml.indexOf(`id="${id}"`);
    assert.ok(start >= 0);
    assert.match(sidePanelHtml.slice(start, start + 400), /<svg/);
  }
});

test("P2 Side Panel renders safe Markdown for history and streaming responses", () => {
  const context = vm.createContext({ URL });
  vm.runInContext(markdownSource, context, { filename: "markdown.js" });
  const html = context.WebBridgeMarkdown.toSafeHtml([
    "# Result",
    "",
    "- **Done**",
    "- `code`",
    "",
    "| A | B |",
    "|---|---|",
    "| 1 | 2 |",
    "",
    "[safe](https://example.com) [bad](javascript:alert(1))",
    "<script>alert('x')</script>",
  ].join("\n"));

  assert.match(html, /<h1>Result<\/h1>/);
  assert.match(html, /<ul><li><strong>Done<\/strong><\/li>/);
  assert.match(html, /<code>code<\/code>/);
  assert.match(html, /<table>/);
  assert.match(html, /href="https:\/\/example\.com\/"/);
  assert.doesNotMatch(html, /href="javascript:/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("selection context creates and binds a browser session before submitting provenance", async () => {
  let interactionBody = null;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/relay-ticket")) {
        return { ok: true, async json() { return { ticket: "ticket-once" }; } };
      }
      if (url.endsWith("/sessions") && !init.method) {
        return { ok: true, async json() { return { data: [], has_more: false }; } };
      }
      if (url.endsWith("/sessions") && init.method === "POST") {
        return { ok: true, async json() { return { id: "session-1", title: "Browser: Active" }; } };
      }
      if (url.endsWith("/bindings")) {
        return { ok: true, async json() { return []; } };
      }
      if (url.endsWith("/bindings/1") && init.method === "PUT") {
        return { ok: true, async json() { return { tab_id: 1, session_id: "session-1" }; } };
      }
      if (url.endsWith("/interactions") && init.method === "POST") {
        interactionBody = JSON.parse(init.body);
        return { ok: true, async json() { return { status: "accepted", interaction_id: "i-1" }; } };
      }
      throw new Error(`Unexpected fetch ${url} ${init.method || "GET"}`);
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await worker.run("setupContextMenus()");
  const info = {
    menuItemId: "webbridge-ask-selection",
    pageUrl: "https://example.com/docs?token=secret#selection",
    selectionText: "A   selected\n passage",
  };
  const tab = { id: 1, title: "Active", url: "https://example.com/docs" };
  const result = await worker.run(
    `sendContextMenuInteraction(${JSON.stringify(info)}, ${JSON.stringify(tab)})`
  );

  assert.equal(result.status, "accepted");
  assert.equal(interactionBody.delivery, "submit");
  assert.equal(interactionBody.target.session_id, "session-1");
  assert.equal(interactionBody.source.user_gesture, true);
  assert.equal(interactionBody.payload.metadata.context_type, "selection");
  assert.equal(interactionBody.payload.metadata.selection_text, "A selected passage");
  assert.equal(interactionBody.payload.metadata.page_url, "https://example.com/docs");
  assert.equal(worker.storedConfig.lastInteraction.status, "accepted");
  assert.equal(worker.actionCalls[0].kind, "badge");
  assert.equal(worker.actionCalls[0].options.tabId, 1);
  assert.equal(worker.actionCalls[0].options.text, "OK");
  assert.equal(worker.menuItems.length, 3);
  assert.ok(worker.menuItems.every((item) => item.documentUrlPatterns?.includes("https://*/*")));
});

test("quick prompt honors the popup-selected session and rebinds the current tab", async () => {
  let interactionBody = null;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/relay-ticket")) {
        return { ok: true, async json() { return { ticket: "ticket-once" }; } };
      }
      if (url.endsWith("/bindings/1") && init.method === "PUT") {
        return { ok: true, async json() { return { tab_id: 1, session_id: "chosen-session" }; } };
      }
      if (url.endsWith("/interactions") && init.method === "POST") {
        interactionBody = JSON.parse(init.body);
        return { ok: true, async json() { return { status: "accepted", interaction_id: "i-1" }; } };
      }
      throw new Error(`Unexpected fetch ${url} ${init.method || "GET"}`);
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const result = await worker.run(`submitBrowserContext(
    { id: 1, title: "Active", url: "https://example.com/docs" },
    { context_type: "page_metadata", prompt: "Explain this page", metadata: { page_url: "https://example.com/docs", page_title: "Active" } },
    "chosen-session"
  )`);

  assert.equal(result.status, "accepted");
  assert.equal(interactionBody.target.session_id, "chosen-session");
  assert.equal(worker.fetchCalls.some((call) => call.url.endsWith("/sessions")), false);
});

test("retry reuses a pending browser action without creating another session", async () => {
  let sessionCreates = 0;
  const interactionKeys = [];
  let interactionAttempts = 0;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/relay-ticket")) {
        return { ok: true, async json() { return { ticket: "ticket-once" }; } };
      }
      if (url.endsWith("/bindings") && !init.method) {
        return { ok: true, async json() { return []; } };
      }
      if (url.endsWith("/sessions") && init.method === "POST") {
        sessionCreates++;
        return { ok: true, async json() { return { id: "session-1", title: "Browser: Active" }; } };
      }
      if (url.endsWith("/bindings/1") && init.method === "PUT") {
        return { ok: true, async json() { return { tab_id: 1, session_id: "session-1" }; } };
      }
      if (url.endsWith("/interactions") && init.method === "POST") {
        interactionAttempts++;
        interactionKeys.push(init.headers["Idempotency-Key"]);
        if (interactionAttempts === 1) throw new Error("response lost");
        return { ok: true, async json() { return { status: "accepted", interaction_id: "i-1" }; } };
      }
      throw new Error(`Unexpected fetch ${url} ${init.method || "GET"}`);
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const tab = { id: 1, title: "Active", url: "https://example.com/docs" };
  const payload = {
    context_type: "page_metadata",
    prompt: "Explain this page",
    metadata: { page_url: "https://example.com/docs", page_title: "Active" },
  };
  await assert.rejects(worker.run(`submitBrowserContext(${JSON.stringify(tab)}, ${JSON.stringify(payload)})`), /response lost/);
  assert.equal(worker.storedConfig.pendingInteraction.session_id, "session-1");

  const result = await worker.run("retryPendingInteraction()");
  assert.equal(result.status, "accepted");
  assert.equal(sessionCreates, 1);
  assert.equal(interactionAttempts, 2);
  assert.equal(interactionKeys[0], interactionKeys[1]);
  assert.equal(worker.storedConfig.pendingInteraction, undefined);
});

test("retry rejects and clears browser context after cross-origin navigation", async () => {
  const worker = loadWorker({
    storedConfig: {
      pendingInteraction: {
        action_id: "action-1",
        tab_id: 1,
        page_url: "https://example.com/docs",
        payload: { context_type: "page_metadata", prompt: "Explain", metadata: { page_url: "https://example.com/docs" } },
        session_id: "session-1",
        created_at: Date.now(),
      },
    },
  });
  worker.setTabUrl(1, "https://mail.example.net/inbox");

  await assert.rejects(worker.run("retryPendingInteraction()"), /changed origin/);
  assert.equal(worker.storedConfig.pendingInteraction, undefined);
  assert.equal(worker.fetchCalls.length, 0);
});

test("expired pending browser context is purged during status reads", async () => {
  const worker = loadWorker({
    storedConfig: {
      pendingInteraction: {
        action_id: "expired-action",
        tab_id: 1,
        page_url: "https://example.com/docs",
        payload: { context_type: "selection", metadata: { selection_text: "private" } },
        created_at: Date.now() - 10 * 60 * 1000,
      },
    },
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(await worker.run("readPendingInteraction()"), null);
  assert.equal(worker.storedConfig.pendingInteraction, undefined);
});

test("P1 popup context rejects restricted browser pages before any network request", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async () => {
      throw new Error("network must not be reached");
    },
  });

  await assert.rejects(
    worker.run(`submitBrowserContext(
      { id: 1, title: "Settings", url: "chrome://settings" },
      { context_type: "page_metadata", prompt: "Explain", metadata: { page_url: "chrome://settings" } }
    )`),
    /HTTP\(S\) page/
  );
  assert.equal(worker.fetchCalls.length, 0);
});

test("P1 popup session creation rejects restricted browser pages before any network request", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async () => {
      throw new Error("network must not be reached");
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  worker.setTabUrl(1, "chrome://settings");
  let response = null;
  await worker.run(`chrome.runtime.onMessage.emit(
    { type: "create_browser_session" },
    null,
    (value) => { globalThis.createSessionResponse = value; }
  )`);
  await new Promise((resolve) => setImmediate(resolve));
  response = worker.run("globalThis.createSessionResponse");

  assert.equal(response.ok, false);
  assert.match(response.error, /HTTP\(S\) page/);
  assert.equal(worker.fetchCalls.length, 0);
});

test("P3 text watch matches without sending browser context until the user confirms", async () => {
  let interactionBody = null;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/relay-ticket")) {
        return { ok: true, async json() { return { ticket: "ticket-once" }; } };
      }
      if (url.endsWith("/bindings/1") && init.method === "PUT") {
        return { ok: true, async json() { return { tab_id: 1, session_id: "session-1" }; } };
      }
      if (url.endsWith("/interactions") && init.method === "POST") {
        interactionBody = JSON.parse(init.body);
        return { ok: true, async json() { return { status: "accepted", interaction_id: "watch-i" }; } };
      }
      throw new Error(`Unexpected fetch ${url} ${init.method || "GET"}`);
    },
  });
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  worker.setTabUrl(1, "https://example.com/builds");

  const watch = await worker.run(`armTextWatch(
    { id: 1, title: "Build dashboard", url: "https://example.com/builds" },
    "session-1",
    "Build complete",
    15
  )`);
  const fetchCountBeforePoll = worker.fetchCalls.length;
  worker.setScriptResponder(async () => [{ result: true }]);

  const matched = await worker.run("pollTextWatches()");
  assert.equal(matched.length, 1);
  assert.equal(matched[0].id, watch.id);
  assert.equal(worker.fetchCalls.length, fetchCountBeforePoll);
  assert.equal(worker.storedConfig.webbridgeTextWatches[0].state, "matched");
  assert.ok(worker.actionCalls.some((call) => call.kind === "badge" && call.options.text === "W"));

  const result = await worker.run(`sendMatchedTextWatch(${JSON.stringify(watch.id)})`);
  assert.equal(result.status, "accepted");
  assert.equal(interactionBody.target.session_id, "session-1");
  assert.equal(interactionBody.source.user_gesture, true);
  assert.match(interactionBody.payload.prompt, /Build complete/);
  assert.equal(worker.storedConfig.webbridgeTextWatches.length, 0);
  assert.equal(
    worker.fetchCalls.find((call) => call.url.endsWith("/interactions")).init.headers["Idempotency-Key"],
    `${watch.id}:match`,
  );
});

test("P3 text watch cancels on a page-path change without inspecting or sending page content", async () => {
  const worker = loadWorker({
    storedConfig: {
      webbridgeTextWatches: [{
        id: "watch-1",
        tab_id: 1,
        origin: "https://example.com",
        page_url: "https://example.com/builds",
        session_id: "session-1",
        needle: "Build complete",
        state: "armed",
        created_at: Date.now(),
        expires_at: Date.now() + 60_000,
        matched_at: null,
      }],
    },
  });
  worker.setTabUrl(1, "https://example.com/other");

  await worker.run("pollTextWatches()");

  assert.equal(worker.storedConfig.webbridgeTextWatches.length, 0);
  assert.equal(worker.scriptCalls.length, 0);
  assert.equal(worker.fetchCalls.length, 0);
});

test("P3 text watch expiry clears a stale match badge without sending page content", async () => {
  const worker = loadWorker({
    storedConfig: {
      webbridgeTextWatches: [{
        id: "expired-watch",
        tab_id: 1,
        page_url: "https://example.com/active",
        session_id: "session-1",
        needle: "Done",
        state: "matched",
        created_at: Date.now() - 120_000,
        expires_at: Date.now() - 60_000,
        matched_at: Date.now() - 90_000,
      }],
    },
  });

  const watches = await worker.run("readTextWatches()");

  assert.equal(watches.length, 0);
  assert.equal(worker.storedConfig.webbridgeTextWatches.length, 0);
  assert.ok(worker.actionCalls.some((call) => call.kind === "badge" && call.options.text === ""));
  assert.equal(worker.fetchCalls.length, 0);
  assert.equal(worker.scriptCalls.length, 0);
});

test("P3 text watch rejects restricted pages before binding or polling", async () => {
  const worker = loadWorker({
    storedConfig: { relayBase: "ws://127.0.0.1:8000" },
    fetchResponder: async () => {
      throw new Error("network must not be reached");
    },
  });

  await assert.rejects(
    worker.run(`armTextWatch(
      { id: 1, title: "Settings", url: "chrome://settings" },
      "session-1",
      "Ready",
      15
    )`),
    /HTTP\(S\) page/
  );
  assert.equal(worker.fetchCalls.length, 0);
  assert.equal(worker.scriptCalls.length, 0);
});

test("P3 Teach Mode redacts secrets and saves a pairing-scoped semantic draft", async () => {
  let draftBody = null;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/relay-ticket")) {
        return { ok: true, async json() { return { ticket: "ticket-once" }; } };
      }
      if (url.endsWith("/bindings/1") && init.method === "PUT") {
        return { ok: true, async json() { return { tab_id: 1, session_id: "session-1" }; } };
      }
      if (url.endsWith("/teach-drafts") && init.method === "POST") {
        draftBody = JSON.parse(init.body);
        return {
          ok: true,
          async json() {
            return { id: "draft-1", status: "draft", actions: draftBody.actions };
          },
        };
      }
      throw new Error(`Unexpected fetch ${url} ${init.method || "GET"}`);
    },
  });
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  worker.setTabUrl(1, "https://example.com/settings");

  const recording = await worker.run(`startTeachRecording(
    { id: 1, title: "Settings", url: "https://example.com/settings" },
    "session-1"
  )`);
  assert.equal(recording.state, "recording");
  assert.equal(worker.tabMessages.at(-1).message.enabled, true);
  assert.ok(worker.scriptCalls.some((call) => call.files?.includes("teach_recorder.js")));

  const tab = { id: 1, url: "https://example.com/settings" };
  await worker.run(`recordTeachAction(${JSON.stringify(tab)}, {
    kind: "fill", selector: "#email", value: "me@example.com"
  })`);
  await worker.run(`recordTeachAction(${JSON.stringify(tab)}, {
    kind: "fill", selector: "#password", secret: true, parameter: "account_password", value: "never-store-me"
  })`);
  await worker.run(`recordTeachAction(${JSON.stringify(tab)}, {
    kind: "click", selector: "button[type=submit]"
  })`);
  const draft = await worker.run("finishTeachRecording()");

  assert.equal(draft.id, "draft-1");
  assert.equal(draftBody.session_id, "session-1");
  assert.equal(draftBody.actions.length, 3);
  assert.deepEqual(draftBody.actions[1], {
    kind: "fill",
    selector: "#password",
    secret: true,
    parameter: "account_password",
  });
  assert.equal(JSON.stringify(draftBody).includes("never-store-me"), false);
  assert.equal(worker.storedConfig.webbridgeTeachRecording, undefined);
  assert.equal(worker.storedConfig.lastTeachDraft.id, "draft-1");
});

test("P3 Teach recorder classifies OTP and security-answer values as secret at source", async () => {
  const recorder = loadTeachRecorder();
  const otp = new recorder.FakeInput({
    id: "otp",
    autocomplete: "one-time-code",
    value: "123456",
  });
  const securityAnswer = new recorder.FakeTextArea({
    id: "security-answer",
    name: "security_answer",
    value: "private answer",
  });
  const accessToken = new recorder.FakeInput({
    id: "accessToken",
    value: "private-token",
  });
  const creditCard = new recorder.FakeInput({
    name: "creditCardNumber",
    value: "4111111111111111",
  });

  recorder.listeners.change({ isTrusted: true, target: otp });
  recorder.listeners.change({ isTrusted: true, target: securityAnswer });
  recorder.listeners.change({ isTrusted: true, target: accessToken });
  recorder.listeners.change({ isTrusted: true, target: creditCard });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(recorder.sent.length, 4);
  assert.ok(recorder.sent.every((message) => message.action.secret === true));
  assert.equal(JSON.stringify(recorder.sent).includes("123456"), false);
  assert.equal(JSON.stringify(recorder.sent).includes("private answer"), false);
  assert.equal(JSON.stringify(recorder.sent).includes("private-token"), false);
  assert.equal(JSON.stringify(recorder.sent).includes("4111111111111111"), false);
  assert.deepEqual(
    recorder.sent.map((message) => message.action.parameter),
    ["otp", "security_answer", "accessToken", "creditCardNumber"],
  );
});

test("P3 Teach Mode ignores a stale same-origin content-script message after navigation", async () => {
  const worker = loadWorker({
    storedConfig: {
      webbridgeTeachRecording: {
        id: "teach-1",
        tab_id: 1,
        session_id: "session-1",
        origin: "https://example.com",
        start_url: "https://example.com/start",
        current_page_url: "https://example.com/next",
        title: "Recorded flow",
        state: "recording",
        actions: [],
      },
    },
  });
  worker.setTabUrl(1, "https://example.com/next");

  const result = await worker.run(`recordTeachAction(
    { id: 1, url: "https://example.com/next" },
    { kind: "click", selector: "#stale" },
    "https://example.com/start"
  )`);

  assert.equal(result, null);
  assert.equal(worker.storedConfig.webbridgeTeachRecording.actions.length, 0);
});

test("P3 Teach Mode stops capturing after cross-origin navigation", async () => {
  const worker = loadWorker({
    storedConfig: {
      webbridgeTeachRecording: {
        id: "teach-1",
        tab_id: 1,
        session_id: "session-1",
        origin: "https://example.com",
        start_url: "https://example.com/start",
        current_page_url: "https://example.com/start",
        title: "Recorded flow",
        state: "recording",
        actions: [],
      },
    },
  });

  await worker.run(`handleTeachTabUpdate(1, {
    url: "https://other.example/account",
    status: "complete"
  })`);

  assert.equal(worker.storedConfig.webbridgeTeachRecording.state, "ready");
  assert.match(worker.storedConfig.webbridgeTeachRecording.stop_reason, /cross-origin/);
  assert.equal(worker.tabMessages.at(-1).message.enabled, false);
});

test("P2 opens the Chrome Side Panel for the active tab", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  let response = null;

  await worker.run(`chrome.runtime.onMessage.emit(
    { type: "open_side_panel" },
    null,
    (value) => { globalThis.sidePanelResponse = value; }
  )`);
  await new Promise((resolve) => setImmediate(resolve));
  response = worker.run("globalThis.sidePanelResponse");

  assert.equal(response.ok, true);
  assert.equal(response.tab_id, 1);
  assert.ok(worker.sidePanelCalls.some((call) => call.kind === "open" && call.options.tabId === 1));
});

test("P2 human control lease blocks agent commands until the user resumes", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));

  const lease = await worker.run("(async () => takeHumanControlLease(await getActiveTab()))()");
  assert.equal(lease.tab_id, 1);
  assert.equal(lease.origin, "https://example.com");
  await assert.rejects(worker.run("resolveTab({ tab_id: 1 })"), /Human control is active/);
  await assert.rejects(worker.run("cmdSwitchTab({ id: 2 })"), /Human control is active/);
  await assert.rejects(worker.run("cmdOpenTab({ url: 'https://example.com/new', active: true })"), /Human control is active/);
  await assert.rejects(worker.run("cmdCloseTab({ id: 1 })"), /Human control is active/);

  const second = await worker.run("(async () => takeHumanControlLease(await chrome.tabs.get(2)))()");
  assert.equal(second.tab_id, 2);
  assert.equal(Object.keys(worker.storedSession.webbridgeHumanControlLease).length, 2);

  assert.equal(await worker.run("releaseHumanControlLease(1)"), true);
  assert.equal(Object.keys(worker.storedSession.webbridgeHumanControlLease).length, 1);
  const tab = await worker.run("resolveTab({ tab_id: 1 })");
  assert.equal(tab.id, 1);
  await assert.rejects(worker.run("cmdCloseTab({ id: 1 })"), /Human control is active/);
  assert.equal(await worker.run("releaseHumanControlLease(2)"), true);
});

test("P2 element picker stores only a sanitized semantic anchor", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  const tab = { id: 1, url: "https://example.com/active" };

  const element = await worker.run(`savePickedElement(${JSON.stringify(tab)}, {
    page_url: "https://example.com/active?private=1",
    selector: "#password",
    tag: "input",
    role: "textbox",
    name: "Password",
    text: "",
    value: "must-not-survive"
  })`);

  assert.equal(element.selector, "#password");
  assert.equal(element.name, "Password");
  assert.equal("value" in element, false);
  assert.equal(JSON.stringify(worker.storedSession).includes("must-not-survive"), false);
  assert.ok(worker.storedSession.webbridgePickedElements[1]);
});

test("P2 element picker retries activation and renders page guidance", async () => {
  let attempts = 0;
  const worker = loadWorker({
    async tabMessageResponder(_tabId, message) {
      if (message.type !== "webbridge_element_picker") return { ok: true };
      attempts += 1;
      if (attempts === 1) throw new Error("Receiving end does not exist");
      return { ok: true };
    },
  });
  await new Promise((resolve) => setImmediate(resolve));

  const result = await worker.run("startElementPicker({ id: 1, url: 'https://example.com/active' })");

  assert.equal(result.tab_id, 1);
  assert.equal(attempts, 2);
  assert.ok(worker.scriptCalls.some((call) => call.files?.includes("element_picker.js")));
  const pickerSource = fs.readFileSync(path.join(__dirname, "..", "extensions", "webbridge", "element_picker.js"), "utf8");
  assert.match(pickerSource, /Pick an element · Esc to cancel/);
  assert.match(pickerSource, /function start\(\) \{\s+if \(enabled\) return;/);
  assert.match(pickerSource, /document\.documentElement\.style\.cursor = previousCursor/);
});

test("paired connection exchanges credential for a single-use relay ticket", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async () => ({
      ok: true,
      async json() {
        return { ticket: "ticket-once", expires_in: 30 };
      },
    }),
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.fetchCalls.length, 1);
  assert.equal(worker.fetchCalls[0].url, "http://127.0.0.1:8000/api/team/webbridge/relay-ticket");
  assert.equal(worker.fetchCalls[0].init.headers.Authorization, "Bearer pair-secret");
  assert.equal(worker.sockets.length, 1);
  assert.equal(
    worker.sockets[0].url,
    "ws://127.0.0.1:8000/api/team/webbridge/relay?_ticket=ticket-once"
  );
  assert.equal(worker.sockets[0].url.includes("pair-secret"), false);

  worker.sockets[0].readyState = worker.context.WebSocket.OPEN;
  worker.sockets[0].onopen();
  const register = JSON.parse(worker.sockets[0].sent[0]);
  assert.equal(register.protocol_version, 2);
  assert.ok(register.capabilities.commands.includes("snapshot"));
  assert.deepEqual(register.capabilities.interactions, ["context.share", "prompt.submit"]);
  assert.ok(register.capabilities.ui.includes("side_panel"));
  assert.ok(register.capabilities.handoff.includes("human_control_lease"));
  assert.ok(register.capabilities.automation.includes("teach_mode"));
});

test("pairing code exchange persists the scoped credential", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "wss://evoflux.example",
      accessToken: "legacy-secret",
    },
    fetchResponder: async () => ({
      ok: true,
      async json() {
        return {
          pairing_id: "pairing-2",
          credential: "scoped-secret",
          scopes: ["relay", "interactions:write"],
        };
      },
    }),
  });

  const result = await worker.run('pairWithCode("ABCD-EFGH-JKLM")');

  assert.equal(worker.fetchCalls.at(-1).url, "https://evoflux.example/api/team/webbridge/pairing/exchange");
  assert.equal(worker.fetchCalls.at(-1).init.method, "POST");
  assert.deepEqual(JSON.parse(worker.fetchCalls.at(-1).init.body), {
    code: "ABCD-EFGH-JKLM",
    browser: "chrome",
    version: "test",
  });
  assert.equal(worker.storedConfig.pairingCredential, "scoped-secret");
  assert.equal(worker.storedConfig.pairingId, "pairing-2");
  assert.equal(worker.storedConfig.pairingRelayBase, "wss://evoflux.example");
  assert.equal(worker.storedConfig.accessToken, undefined);
  assert.equal(result.pairing_id, "pairing-2");
});

test("legacy stored access token is removed and cannot open the relay", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      accessToken: "must-be-deleted",
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.storedConfig.accessToken, undefined);
  assert.equal(worker.sockets.length, 0);
  assert.equal(worker.fetchCalls.length, 0);
  assert.equal(worker.run("lastCloseReason"), "pairing");
});

test("local loopback pairing persists a scoped credential without a code", async () => {
  const worker = loadWorker({
    storedConfig: { relayBase: "ws://127.0.0.1:8000" },
    fetchResponder: async (url, init) => {
      assert.equal(url, "http://127.0.0.1:8000/api/team/webbridge/pairing/local");
      assert.equal(init.method, "POST");
      return {
        ok: true,
        async json() {
          return {
            pairing_id: "pairing-local",
            credential: "local-scoped-secret",
            scopes: ["relay", "interactions:write"],
          };
        },
      };
    },
  });

  const result = await worker.run("pairLocally()");

  assert.equal(result.pairing_id, "pairing-local");
  assert.equal(worker.storedConfig.pairingCredential, "local-scoped-secret");
  assert.equal(worker.storedConfig.pairingRelayBase, "ws://127.0.0.1:8000");
});

test("revoked pairing credential is removed before reconnect", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "revoked-secret",
      pairingId: "pairing-revoked",
      pairingRelayBase: "ws://127.0.0.1:8000",
    },
    fetchResponder: async () => ({
      ok: false,
      status: 401,
      async json() {
        return { detail: { message: "Pair WebBridge first." } };
      },
    }),
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.sockets.length, 0);
  assert.equal(worker.storedConfig.pairingCredential, "");
  assert.equal(worker.storedConfig.pairingId, "");
  assert.equal(worker.run("lastCloseReason"), "pairing");
  assert.equal(worker.run("manualDisconnect"), true);
});

test("relay revocation close clears pairing without reconnect", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:8000",
      pairingCredential: "paired-secret",
      pairingId: "pairing-active",
      pairingRelayBase: "ws://127.0.0.1:8000",
      pendingInteraction: { action_id: "private-context", created_at: Date.now() },
      webbridgeTextWatches: [{
        id: "watch-1", tab_id: 1, state: "armed", expires_at: Date.now() + 60_000,
      }],
      webbridgeTeachRecording: { id: "teach-1", tab_id: 1, state: "recording", actions: [] },
    },
    storedSession: {
      webbridgeHumanControlLease: { 1: { tab_id: 1, expires_at: Date.now() + 60_000 } },
      webbridgePickedElements: { 1: { tab_id: 1, selector: "#private" } },
    },
    fetchResponder: async () => ({
      ok: true,
      async json() {
        return { ticket: "ticket-once", expires_in: 30 };
      },
    }),
  });
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const socket = worker.sockets[0];
  socket.readyState = worker.context.WebSocket.OPEN;
  socket.onopen();

  socket.onclose({ code: 4403 });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.storedConfig.pairingCredential, "");
  assert.equal(worker.storedConfig.pairingId, "");
  assert.equal(worker.storedConfig.pendingInteraction, undefined);
  assert.equal(worker.storedConfig.webbridgeTextWatches, undefined);
  assert.equal(worker.storedConfig.webbridgeTeachRecording, undefined);
  assert.equal(worker.storedSession.webbridgeHumanControlLease, undefined);
  assert.equal(worker.storedSession.webbridgePickedElements, undefined);
  assert.equal(worker.run("manualDisconnect"), true);
  assert.equal(worker.sockets.length, 1);
});

test("pairing credential is never sent after relay URL changes", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "wss://different.example",
      pairingCredential: "relay-bound-secret",
      pairingId: "pairing-bound",
      pairingRelayBase: "wss://original.example",
    },
    fetchResponder: async () => {
      throw new Error("credential must not be sent");
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.fetchCalls.length, 0);
  assert.equal(worker.sockets.length, 0);
  assert.equal(worker.storedConfig.pairingCredential, "");
  assert.equal(worker.run("lastCloseReason"), "pairing");
});

test("insecure remote relay is rejected before network access", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://relay.example",
      pairingCredential: "must-not-leak",
      pairingId: "pairing-insecure",
      pairingRelayBase: "ws://relay.example",
    },
    fetchResponder: async () => {
      throw new Error("network must not be reached");
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.fetchCalls.length, 0);
  assert.equal(worker.sockets.length, 0);
  assert.equal(worker.run("lastCloseReason"), "security");
  assert.equal(worker.run("manualDisconnect"), true);
});

test("middle click is preserved in both CDP events", async () => {
  const worker = loadWorker();

  const result = await worker.run('cmdClick({ x: 10, y: 20, button: "middle" })');

  assert.equal(result.button, "middle");
  const mouseCalls = worker.cdpCalls.filter((call) => call.method === "Input.dispatchMouseEvent");
  assert.deepEqual(mouseCalls.map((call) => call.params.button), ["middle", "middle"]);
});

test("bound-origin guard rejects a tab that navigated before a command executes", async () => {
  const worker = loadWorker();

  await assert.rejects(
    worker.run(`resolveTab({ tab_id: 1, _webbridge_expected_origin: "https://other.example" })`),
    /changed origin/
  );
});

test("key modifiers become the CDP modifier bitmask", async () => {
  const worker = loadWorker();

  await worker.run('cmdKey({ key: "a", modifiers: ["Meta", "Shift"] })');

  const keyCalls = worker.cdpCalls.filter((call) => call.method === "Input.dispatchKeyEvent");
  assert.equal(keyCalls.length, 2);
  assert.ok(keyCalls.every((call) => call.params.modifiers === 12));
  assert.ok(keyCalls.every((call) => call.params.code === "KeyA"));
});

test("evaluate reports page exceptions instead of returning success", async () => {
  const worker = loadWorker();
  worker.setCdpResponder((method) =>
    method === "Runtime.evaluate"
      ? { exceptionDetails: { text: "Uncaught", exception: { description: "ReferenceError: nope" } } }
      : {}
  );

  await assert.rejects(worker.run('cmdEvaluate({ script: "nope" })'), /ReferenceError: nope/);
});

test("tab broadcasts include pending background URLs", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  worker.context.sentFrames = [];
  worker.run(`
    ws = {
      readyState: WebSocket.OPEN,
      send(message) { globalThis.sentFrames.push(message); },
    };
  `);
  await worker.run("broadcastTabInfo()");

  const frame = JSON.parse(worker.context.sentFrames.at(-1));
  assert.equal(frame.event, "tab_updated");
  assert.equal(frame.data.tabs[1].url, "https://example.com/pending");
  assert.equal(frame.data.tabs[1].pinned, true);
});

test("release detaches every tab controlled by the extension", async () => {
  const worker = loadWorker();
  await worker.run("ensureDebuggerAttached(1)");
  await worker.run("ensureDebuggerAttached(2)");

  const released = await worker.run("detachAllDebuggers()");

  assert.deepEqual([...released], [1, 2]);
  assert.deepEqual(worker.detachedTabs, [1, 2]);
});