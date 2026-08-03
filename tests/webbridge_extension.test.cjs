"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const nativeSetTimeout = globalThis.setTimeout;
const nativeClearTimeout = globalThis.clearTimeout;
const workerTimers = new Set();

test.afterEach(async () => {
  await new Promise((resolve) => setImmediate(resolve));
  for (const timer of workerTimers) nativeClearTimeout(timer);
  workerTimers.clear();
});

const workerSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "background.js"),
  "utf8"
);
const semanticRuntimeSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "semantic_runtime.js"),
  "utf8"
);
const teachRecorderSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "teach_recorder.js"),
  "utf8"
);
const agentControlOverlaySource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "agent_control_overlay.js"),
  "utf8"
);
const textWatchSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "text_watch.js"),
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
  const nativeMessageCalls = [];
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
    sendNativeMessage(host, message, callback) {
      nativeMessageCalls.push({ host, message });
      if (options.nativeMessageResponder) {
        options.nativeMessageResponder(host, message, callback, runtime);
        return;
      }
      if (storedConfig.pairingCredential) {
        callback({
          ok: true,
          protocol_version: 1,
          app_pid: 4242,
          base_url: (storedConfig.relayBase || "ws://127.0.0.1:4082").replace(/^ws:/, "http:"),
          discovery_token: "default-native-discovery-token-long-enough",
        });
        return;
      }
      runtime.lastError = { message: "Specified native messaging host not found." };
      callback(undefined);
      runtime.lastError = null;
    },
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

  let context;
  context = vm.createContext({
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
    importScripts(...files) {
      for (const file of files) {
        const source = file === "semantic_runtime.js"
          ? semanticRuntimeSource
          : fs.readFileSync(path.join(__dirname, "..", "extensions", "webbridge", file), "utf8");
        vm.runInContext(source, context, { filename: file });
      }
    },
    clearTimeout(timer) {
      workerTimers.delete(timer);
      nativeClearTimeout(timer);
    },
    setTimeout(callback, delay, ...args) {
      let timer;
      timer = nativeSetTimeout(() => {
        workerTimers.delete(timer);
        callback(...args);
      }, delay);
      workerTimers.add(timer);
      return timer;
    },
  });
  vm.runInContext(workerSource, context, { filename: "background.js" });

  return {
    cdpCalls,
    context,
    detachedTabs,
    fetchCalls,
    menuItems,
    nativeMessageCalls,
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

function loadTextWatchRuntime() {
  const sent = [];
  const body = { innerText: "Waiting for build", textContent: "Waiting for build" };
  class FakeMutationObserver {
    constructor(callback) { this.callback = callback; }
    observe() {}
    disconnect() {}
  }
  const context = vm.createContext({
    chrome: {
      runtime: {
        onMessage: eventChannel(),
        async sendMessage(message) { sent.push(message); return { ok: true }; },
      },
    },
    document: { body, documentElement: {} },
    location: { href: "https://example.com/builds" },
    MutationObserver: FakeMutationObserver,
    setTimeout,
    clearTimeout,
  });
  vm.runInContext(textWatchSource, context, { filename: "text_watch.js" });
  return { body, context, sent };
}

test("P2 Side Chat auto-creates and binds one session for an unbound tab", async () => {
  let atomicCreates = 0;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/bindings") && !init.method) {
        return { ok: true, async json() { return []; } };
      }
      if (url.endsWith("/bindings/1/sessions") && init.method === "POST") {
        atomicCreates += 1;
        return {
          ok: true,
          async json() {
            return {
              session: { id: "session-auto", title: "Browser: Active" },
              binding: {
                tab_id: 1,
                session_id: "session-auto",
                origin: "https://example.com",
              },
            };
          },
        };
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
  assert.equal(response.tab.group_id, -1);
  assert.equal(atomicCreates, 1);
  assert.equal(worker.tabGroupCalls.filter((call) => call.kind === "group").length, 0);
  assert.equal((await worker.run("chrome.tabs.get(1)")).groupId, undefined);
});

test("P2 Side Chat hides chat-session selection and always ensures the active tab session", () => {
  assert.doesNotMatch(sidePanelHtml, /sessionSelect|Choose conversation|Start fresh conversation/);
  assert.doesNotMatch(sidePanelSource, /bindSelectedSession|startFreshConversation|resolve_browser_session_for_tab/);
  assert.match(sidePanelSource, /type: "ensure_browser_session_for_tab"/);
  assert.match(sidePanelHtml, /Primary tab · group starts with a second tab/);
  assert.match(workerSource, /createAndBindBrowserSession/);
  assert.match(workerSource, /\$\{BINDINGS_PATH\}\/\$\{encodeURIComponent\(tab\.id\)\}\/sessions/);
});

test("P2 internal tab keeps one session and upgrades its HTTP tool scope", async () => {
  let sessionCreates = 0;
  const bindings = [];
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/bindings") && !init.method) {
        return { ok: true, async json() { return bindings.map((item) => ({ ...item })); } };
      }
      if (url.endsWith("/bindings/1/sessions") && init.method === "POST") {
        sessionCreates += 1;
        const body = JSON.parse(init.body);
        bindings.splice(0, bindings.length, {
          tab_id: 1,
          session_id: "session-internal",
          origin: body.origin,
        });
        return {
          ok: true,
          async json() {
            return {
              session: { id: "session-internal", title: "Browser: New Tab" },
              binding: bindings[0],
            };
          },
        };
      }
      if (url.endsWith("/bindings/1") && init.method === "PUT") {
        const body = JSON.parse(init.body);
        bindings.splice(0, bindings.length, {
          tab_id: 1,
          session_id: body.session_id,
          origin: body.origin,
        });
        return { ok: true, async json() { return bindings[0]; } };
      }
      throw new Error(`Unexpected fetch ${url} ${init.method || "GET"}`);
    },
  });
  await new Promise((resolve) => setImmediate(resolve));
  worker.setTabUrl(1, "chrome://newtab/");

  const internal = await worker.run(`new Promise((resolve) => chrome.runtime.onMessage.emit(
    { type: "ensure_browser_session_for_tab", action_id: "internal-tab" }, null, resolve
  ))`);
  assert.equal(internal.ok, true);
  assert.equal(internal.session_id, "session-internal");
  assert.equal(internal.binding_origin, "tab:1");
  assert.equal(bindings[0].origin, "tab:1");

  worker.setTabUrl(1, "https://example.com/app");
  const upgraded = await worker.run(`new Promise((resolve) => chrome.runtime.onMessage.emit(
    { type: "ensure_browser_session_for_tab", action_id: "same-tab" }, null, resolve
  ))`);
  assert.equal(upgraded.session_id, "session-internal");
  assert.equal(upgraded.binding_origin, "https://example.com");
  assert.equal(bindings[0].origin, "https://example.com");
  assert.equal(sessionCreates, 1);
});

test("P2 internal pages keep chat enabled while page tools wait for HTTP", () => {
  assert.match(sidePanelSource, /function browserTabScope\(tab\)/);
  assert.match(sidePanelSource, /Primary tab/);
  assert.match(sidePanelSource, /Group tab/);
  assert.match(sidePanelSource, /Browser tools activate on HTTP\(S\) pages/);
  assert.match(sidePanelSource, /origin: sourceScope/);
  assert.doesNotMatch(sidePanelSource, /Side Chat only works on HTTP\(S\) pages/);
  assert.doesNotMatch(sidePanelSource, /Open an HTTP\(S\) page to start a conversation/);
});

test("P2 extension action opens Side Chat and settings live inside the panel", () => {
  assert.equal(extensionManifest.action.default_popup, undefined);
  assert.equal(extensionManifest.content_scripts, undefined);
  assert.equal(extensionManifest.web_accessible_resources, undefined);
  assert.ok(extensionManifest.permissions.includes("tabGroups"));
  assert.ok(extensionManifest.permissions.includes("nativeMessaging"));
  assert.ok(extensionManifest.key);
  assert.match(workerSource, /openPanelOnActionClick: true/);
  assert.match(sidePanelHtml, /id="settingsDrawer"/);
  assert.match(sidePanelHtml, /id="relayBaseInput"/);
  assert.match(sidePanelHtml, /Discovered desktop endpoint/);
  assert.match(sidePanelHtml, /id="relayBaseInput"[^>]+readonly/);
  assert.doesNotMatch(sidePanelHtml, /pairLocalBtn|pairingCodeInput|pairCodeBtn|Manual or remote pairing/);
  assert.doesNotMatch(workerSource, /pair_with_code|pair_locally|PAIRING_EXCHANGE_PATH/);
  assert.doesNotMatch(sidePanelHtml, /id="sessionSelect"|newConversation/);
  assert.match(sidePanelSource, /ensure_browser_session_for_tab/);
  assert.doesNotMatch(sidePanelHtml, /Legacy access token|accessTokenInput/);
  assert.doesNotMatch(workerSource, /[?&]_token=/);
  assert.doesNotMatch(workerSource, /ui: \["popup"/);
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

test("P2 region capture uses CSS viewport geometry without multiplying DPR", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  worker.setCdpResponder((method) => {
    if (method === "Page.getLayoutMetrics") {
      return {
        cssVisualViewport: {
          clientWidth: 1280,
          clientHeight: 720,
          pageX: 30,
          pageY: 400,
          scale: 1.25,
        },
      };
    }
    if (method === "Page.captureScreenshot") return { data: "cG5n" };
    return {};
  });

  const capture = await worker.run(`captureSelectedRegion(
    { id: 1, url: "https://example.com/active" },
    {
      page_url: "https://example.com/active",
      clip: { x: 100, y: 50, width: 320, height: 180 },
      viewport: { width: 1280, height: 720, page_x: 30, page_y: 400, scale: 1.25, dpr: 2 }
    }
  )`);

  assert.equal(capture.data_base64, "cG5n");
  const screenshot = worker.cdpCalls.find((call) => call.method === "Page.captureScreenshot");
  assert.deepEqual(JSON.parse(JSON.stringify(screenshot.params.clip)), {
    x: 130,
    y: 450,
    width: 320,
    height: 180,
    scale: 1,
  });
  assert.equal(screenshot.params.captureBeyondViewport, true);
  assert.equal(worker.storedSession.webbridgeRegionCaptures[1].page_url, "https://example.com/active");

  const picker = await worker.run("startRegionPicker({ id: 1, url: 'https://example.com/active' })");
  assert.equal(picker.tab_id, 1);
  assert.ok(worker.scriptCalls.some((call) => call.files?.includes("region_picker.js")));
  assert.ok(worker.tabMessages.some((call) => call.message.type === "webbridge_region_picker"));
});

test("P2 panel context capture is explicit bounded and excludes form controls", async () => {
  const worker = loadWorker({
    scriptResponder: (options) => [{
      result: {
        type: options.args[0],
        page_url: "https://example.com/active",
        title: "Active page",
        text: "Selected text",
      },
    }],
  });
  await new Promise((resolve) => setImmediate(resolve));

  const context = await worker.run("capturePanelContext({ id: 1, url: 'https://example.com/active' }, 'selection')");
  assert.equal(context.type, "selection");
  assert.equal(context.text, "Selected text");
  const call = worker.scriptCalls.at(-1);
  assert.deepEqual(JSON.parse(JSON.stringify(call.target.frameIds)), [0]);
  assert.equal(call.args[1], 20000);
  const source = call.func.toString();
  assert.match(source, /window\.getSelection/);
  assert.match(source, /input,textarea,select,option/);
  assert.match(workerSource, /msg\.type === "capture_panel_context"/);
});

test("semantic snapshot keeps backend node ids opaque and writes require readback", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  let currentValue = "Before";
  worker.setCdpResponder((method, params) => {
    if (method === "Page.getFrameTree") {
      return { frameTree: { frame: { id: "root-frame" } } };
    }
    if (method === "Accessibility.enable") return {};
    if (method === "Accessibility.getFullAXTree") {
      return {
        nodes: [{
          nodeId: "ax-1",
          backendDOMNodeId: 987,
          frameId: "root-frame",
          ignored: false,
          role: { value: "textbox" },
          name: { value: "Document editor" },
          value: { value: currentValue },
          properties: [{ name: "editable", value: { value: true } }],
        }],
      };
    }
    if (method === "DOM.resolveNode") {
      assert.equal(params.backendNodeId, 987);
      return { object: { objectId: "object-1" } };
    }
    if (method === "Runtime.callFunctionOn") {
      if (String(params.functionDeclaration).includes("setSelectionRange")) {
        return { result: { value: { status: "ok" } } };
      }
      return {
        result: {
          value: { status: "ok", text: currentValue, editable: true },
        },
      };
    }
    if (method === "Input.insertText") {
      currentValue = params.text;
      return {};
    }
    return {};
  });

  const snapshot = await worker.run("WebBridgeSemantic.snapshot({ max_items: 10, include_values: false })");
  assert.equal(snapshot.status, "ok");
  assert.equal(snapshot.items.length, 1);
  assert.equal(snapshot.items[0].target.kind, "ref");
  assert.equal(JSON.stringify(snapshot).includes("987"), false);
  assert.equal(JSON.stringify(snapshot).includes("backendDOMNodeId"), false);

  const target = JSON.stringify(snapshot.items[0].target);
  const written = await worker.run(`WebBridgeSemantic.write({
    target: ${target},
    change: { kind: "text", mode: "replace", at: "caret", text: "After" },
    verify: "normalized"
  })`);
  assert.equal(written.status, "ok");
  assert.equal(written.readback, "After");
  assert.equal(written.persistence, "not_checked");

  const unsupported = await worker.run(`WebBridgeSemantic.read({
    target: { kind: "range", address: "B2:C3", sheet: null },
    value_mode: "both"
  })`);
  assert.equal(unsupported.status, "unsupported");
  assert.equal(unsupported.code, "adapter_not_detected");
});

test("semantic snapshot skips cross-origin frame accessibility content", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  worker.setCdpResponder((method, params) => {
    if (method === "Page.getFrameTree") {
      return {
        frameTree: {
          frame: { id: "root", url: "https://example.com/active" },
          childFrames: [{ frame: { id: "foreign", url: "https://private.example/embedded" } }],
        },
      };
    }
    if (method === "Accessibility.enable") return {};
    if (method === "Accessibility.getFullAXTree" && params.frameId === "root") {
      return {
        nodes: [{
          backendDOMNodeId: 1,
          ignored: false,
          role: { value: "textbox" },
          name: { value: "Root editor" },
          properties: [],
        }],
      };
    }
    if (method === "Accessibility.getFullAXTree" && params.frameId === "foreign") {
      throw new Error("cross-origin frame must not be queried");
    }
    return {};
  });
  const snapshot = await worker.run("WebBridgeSemantic.snapshot({ max_items: 10 })");
  assert.equal(snapshot.items.length, 1);
  assert.equal(snapshot.items[0].name, "Root editor");
  assert.ok(snapshot.warnings.some((warning) => warning.includes("Cross-origin frame")));
  assert.equal(worker.cdpCalls.some((call) => call.method === "Accessibility.getFullAXTree" && call.params.frameId === "foreign"), false);
});

test("semantic spreadsheet writes refuse named sheets and skip cells before mutation", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  worker.setTabUrl(1, "https://docs.google.com/spreadsheets/d/example/edit");
  worker.setCdpResponder((method) => {
    if (method === "Page.getFrameTree") {
      return {
        frameTree: {
          frame: {
            id: "sheet-frame",
            url: "https://docs.google.com/spreadsheets/d/example/edit",
          },
        },
      };
    }
    if (method === "Accessibility.enable") return {};
    if (method === "Accessibility.getFullAXTree") {
      return {
        nodes: [{
          nodeId: "grid-1",
          backendDOMNodeId: 100,
          ignored: false,
          role: { value: "grid" },
          name: { value: "Sheet grid" },
          properties: [],
        }],
      };
    }
    if (method === "Input.insertText") {
      throw new Error("unsafe spreadsheet mutation");
    }
    return {};
  });

  const namedSheet = await worker.run(`WebBridgeSemantic.write({
    target: { kind: "range", address: "A1:B1", sheet: "Budget" },
    change: { kind: "matrix", rows: [[{ kind: "value", value: "Q1" }, { kind: "value", value: "Q2" }]] },
    verify: "none"
  })`);
  assert.equal(namedSheet.status, "unsupported");
  assert.equal(namedSheet.code, "sheet_target_unverified");

  const skipCell = await worker.run(`WebBridgeSemantic.write({
    target: { kind: "range", address: "A1:B1", sheet: null },
    change: { kind: "matrix", rows: [[{ kind: "value", value: "Q1" }, { kind: "skip" }]] },
    verify: "none"
  })`);
  assert.equal(skipCell.status, "unsupported");
  assert.equal(skipCell.code, "skip_cell_refused");
  assert.equal(worker.cdpCalls.some((call) => call.method === "Input.insertText"), false);
});

test("semantic slide-object targeting distinguishes slide 1 from slide 10", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  worker.setTabUrl(1, "https://officeapps.live.com/powerpoint/document");
  const resolvedBackendIds = [];
  worker.setCdpResponder((method, params) => {
    if (method === "Page.getFrameTree") {
      return {
        frameTree: {
          frame: {
            id: "slides-frame",
            url: "https://officeapps.live.com/powerpoint/document",
          },
        },
      };
    }
    if (method === "Accessibility.enable") return {};
    if (method === "Accessibility.getFullAXTree") {
      return {
        nodes: [
          {
            nodeId: "slide-10",
            backendDOMNodeId: 1010,
            childIds: ["slide-10-title"],
            ignored: false,
            role: { value: "listitem" },
            name: { value: "Slide 10" },
            properties: [],
          },
          {
            nodeId: "slide-10-title",
            backendDOMNodeId: 1011,
            ignored: false,
            role: { value: "textbox" },
            name: { value: "Wrong title" },
            properties: [],
          },
          {
            nodeId: "slide-1",
            backendDOMNodeId: 1001,
            childIds: ["slide-1-title"],
            ignored: false,
            role: { value: "listitem" },
            name: { value: "Slide 1" },
            properties: [],
          },
          {
            nodeId: "slide-1-title",
            backendDOMNodeId: 1002,
            ignored: false,
            role: { value: "textbox" },
            name: { value: "Correct title" },
            properties: [],
          },
        ],
      };
    }
    if (method === "DOM.resolveNode") {
      resolvedBackendIds.push(params.backendNodeId);
      return { object: { objectId: `object-${params.backendNodeId}` } };
    }
    if (method === "Runtime.callFunctionOn") {
      return {
        result: {
          value: { status: "ok", text: "Correct title", editable: true },
        },
      };
    }
    return {};
  });

  const result = await worker.run(`WebBridgeSemantic.read({
    target: { kind: "slide_object", slide_index: 1, role: "text", ordinal: 0 },
    max_chars: 1000
  })`);

  assert.equal(result.status, "ok");
  assert.equal(result.text, "Correct title");
  assert.deepEqual(resolvedBackendIds, [1002]);
});

test("P2 a session opens child tabs in a named Chrome tab group", async () => {
  let sessionCreates = 0;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
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
  assert.deepEqual(
    JSON.parse(JSON.stringify(worker.tabGroupCalls[0].options.tabIds)),
    [1, 3]
  );
  assert.equal(worker.tabGroupCalls[1].kind, "update");
  assert.equal(worker.tabGroupCalls[1].options.title, "EvoFlux · Active");
  assert.equal(worker.tabGroupCalls.length, 2);
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
  assert.match(sidePanelHtml, /id="loadOlderBtn"/);
  assert.match(sidePanelSource, /next_cursor/);
  assert.match(sidePanelSource, /history\?before=/);
  assert.match(sidePanelSource, /message\.activities/);
  assert.match(sidePanelSource, /Session compacted/);
  assert.match(sidePanelSource, /function renderLiveTurnDetails/);
  assert.match(sidePanelSource, /Thought · \$\{thinkingChars\.toLocaleString\(\)\} chars/);
  assert.match(sidePanelSource, /if \(type === "thinking"\)/);
  assert.match(sidePanelSource, /toolActivities\.set\(key, data\)/);
  assert.match(sidePanelSource, /return "Browsed web"/);
  assert.match(sidePanelSource, /streamTask && streamingSessionId === selectedSessionId/);
  assert.match(sidePanelSource, /Math\.min\(5000, 250 \* 2 \*\*/);
  assert.match(sidePanelSource, /!sawEvent && !\(await isSessionStillRunning\(sessionId\)\)/);
  assert.match(sidePanelSource, /sessionTitle\.textContent = data\.title/);
  assert.doesNotMatch(sidePanelSource, /pageTitle\.textContent = data\.title/);
});

test("P2 Side Chat history continues past empty projected pages", async () => {
  const start = sidePanelSource.indexOf("async function loadHistory");
  const end = sidePanelSource.indexOf("\n}\n\nfunction renderQuestions", start) + 3;
  const paths = [];
  const appended = [];
  let emptyCount = 0;
  const pages = [
    { messages: [], has_more: true, next_cursor: "cursor-1" },
    {
      messages: [{ id: "message-1", role: "assistant", content: "Visible" }],
      has_more: false,
      next_cursor: null,
    },
  ];
  const context = vm.createContext({
    selectedSessionId: "session-1",
    SESSIONS_PATH: "/sessions",
    historyCursor: null,
    historyLoadGeneration: 0,
    transcript: { scrollHeight: 100, scrollTop: 0 },
    loadOlderBtn: { classList: { toggle() {} } },
    async panelFetch(pathname) {
      paths.push(pathname);
      const body = pages.shift();
      return { async json() { return body; } };
    },
    clearTranscript() {},
    showEmptyTranscript() { emptyCount += 1; },
    appendMessage(message) { appended.push(message); },
    requestAnimationFrame(callback) { callback(); },
  });
  vm.runInContext(
    `${sidePanelSource.slice(start, end)}\nglobalThis.runLoadHistory = loadHistory;`,
    context,
    { filename: "sidepanel-history.js" }
  );

  await context.runLoadHistory();

  assert.deepEqual(paths, [
    "/sessions/session-1/history",
    "/sessions/session-1/history?before=cursor-1",
  ]);
  assert.equal(appended.length, 1);
  assert.equal(appended[0].content, "Visible");
  assert.equal(emptyCount, 0);
});

test("P2 Side Chat ignores stale history after a tab-session switch", async () => {
  const start = sidePanelSource.indexOf("async function loadHistory");
  const end = sidePanelSource.indexOf("\n}\n\nfunction renderQuestions", start) + 3;
  let resolveOld;
  const oldResponse = new Promise((resolve) => { resolveOld = resolve; });
  const appended = [];
  const context = vm.createContext({
    selectedSessionId: "session-old",
    SESSIONS_PATH: "/sessions",
    historyCursor: null,
    historyLoadGeneration: 0,
    transcript: { scrollHeight: 100, scrollTop: 0 },
    loadOlderBtn: { classList: { toggle() {} } },
    async panelFetch(pathname) {
      if (pathname.includes("session-old")) return oldResponse;
      return {
        async json() {
          return {
            messages: [{ id: "fresh", role: "assistant", content: "Fresh session" }],
            has_more: false,
            next_cursor: null,
          };
        },
      };
    },
    clearTranscript() {},
    showEmptyTranscript() {},
    appendMessage(message) { appended.push(message); },
    requestAnimationFrame(callback) { callback(); },
  });
  vm.runInContext(
    `${sidePanelSource.slice(start, end)}\nglobalThis.runLoadHistory = loadHistory;`,
    context,
    { filename: "sidepanel-history-race.js" }
  );

  const staleLoad = context.runLoadHistory();
  context.selectedSessionId = "session-fresh";
  const freshLoad = context.runLoadHistory();
  resolveOld({
    async json() {
      return {
        messages: [{ id: "stale", role: "assistant", content: "Stale session" }],
        has_more: false,
        next_cursor: null,
      };
    },
  });
  await Promise.all([staleLoad, freshLoad]);

  assert.deepEqual(appended.map((message) => message.id), ["fresh"]);
});

test("P2 composer mirrors desktop model settings and icon-only browser controls", () => {
  assert.match(sidePanelHtml, /id="modelTrigger"/);
  assert.match(sidePanelHtml, /id="modelSearch"/);
  assert.match(sidePanelHtml, /id="modelList"/);
  assert.match(sidePanelHtml, /id="modelCurrentName"/);
  assert.match(sidePanelHtml, /id="modelCurrentId"/);
  assert.match(sidePanelHtml, /id="thinkingOptions"/);
  assert.match(sidePanelHtml, /id="speedControl"/);
  assert.match(sidePanelHtml, /data-speed="standard"/);
  assert.match(sidePanelHtml, /data-speed="fast"/);
  assert.match(sidePanelSource, /\/api\/team\/webbridge\/models/);
  assert.match(sidePanelSource, /\/model`/);
  assert.match(sidePanelSource, /thinking_level: thinkingLevel \|\| null/);
  assert.match(sidePanelSource, /fast_mode: currentSessionFastMode/);
  assert.match(sidePanelSource, /function reconcileThinkingLevel/);
  assert.match(sidePanelSource, /function supportsFastMode/);
  assert.match(sidePanelSource, /Model settings synced from EvoFlux/);
  assert.match(sidePanelSource, /function renderComposerSubmitControl/);
  assert.match(sidePanelSource, /Queue a follow-up or stop the run/);
  assert.match(sidePanelHtml, /class="stop-glyph"/);
  for (const id of ["attachPageBtn", "attachSelectionBtn", "captureRegionBtn", "attachFileBtn", "pickElementBtn", "takeControlBtn", "resumeAgentBtn", "sendBtn"]) {
    const start = sidePanelHtml.indexOf(`id="${id}"`);
    assert.ok(start >= 0);
    assert.match(sidePanelHtml.slice(start, start + 400), /<svg/);
  }
  assert.match(sidePanelSource, /messages\/screenshot/);
  assert.match(sidePanelSource, /new FormData\(\)/);
  assert.match(sidePanelSource, /capture_panel_context/);
  assert.match(sidePanelSource, /start_region_picker/);
  assert.match(sidePanelSource, /messages\/attachments/);
  assert.match(sidePanelSource, /function selectPanelFiles/);
  assert.match(sidePanelHtml, /id="openInEvoFluxBtn"/);
  assert.match(sidePanelSource, /function openInEvoFlux/);
});

test("P2 AskUser view replaces the composer until the pending question is answered", () => {
  assert.match(sidePanelHtml, /\.panel\.asking \.activity, \.panel\.asking \.composer \{ display: none; \}/);
  assert.match(sidePanelHtml, /\.panel\.asking \.questions \{ max-height: 65%;/);
  assert.match(sidePanelSource, /panelRoot\.classList\.toggle\("asking", asking\)/);
  assert.match(sidePanelSource, /composerRoot\.toggleAttribute\("inert", asking\)/);
  assert.match(sidePanelSource, /questionsRoot\.querySelector\("textarea\.answer:not\(\[hidden\]\)"\)\?\.focus\(\)/);
  assert.match(sidePanelSource, /requestAnimationFrame\(\(\) => composer\.focus\(\)\)/);
});

test("P2 typed browser handoffs reuse AskUser without reading secret values", () => {
  assert.match(sidePanelSource, /browser_handoff/);
  assert.match(sidePanelSource, /provide_secret/);
  assert.match(sidePanelSource, /No secret is read/);
  assert.match(sidePanelSource, /Done · Resume agent/);
  assert.match(sidePanelSource, /await resumeAgent\(\)/);
  assert.doesNotMatch(sidePanelSource, /passwordValue|secretValue|readSecret/);
});

test("P2 report issue is opt in redacted and uses the artifact route", () => {
  assert.match(sidePanelHtml, /id="issueCaptureBtn"/);
  assert.match(sidePanelHtml, /id="reportIssueBtn"/);
  assert.match(sidePanelSource, /start_issue_capture/);
  assert.match(sidePanelSource, /collect_issue_report/);
  assert.match(sidePanelSource, /messages\/screenshot/);
  assert.match(workerSource, /redactDiagnosticText/);
  assert.match(workerSource, /MAX_DIAGNOSTIC_ENTRIES = 30/);
  assert.doesNotMatch(workerSource, /request\.headers|postData|responseBody/);
});

test("P2 issue collector is opt in and redacts sensitive diagnostics", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  worker.setCdpResponder(() => ({}));

  await worker.run(`chrome.debugger.onEvent.emit(
    { tabId: 1 },
    "Runtime.consoleAPICalled",
    { type: "error", args: [{ value: "token=before https://example.com/path?secret=1" }] }
  )`);
  assert.equal(await worker.run("diagnosticCaptures.size"), 0);

  await worker.run("startDiagnosticCapture({ id: 1, url: 'https://example.com/active' })");
  assert.equal(await worker.run("agentControlOverlays.has(1)"), false);
  await worker.run(`chrome.debugger.onEvent.emit(
    { tabId: 1 },
    "Runtime.consoleAPICalled",
    { type: "error", args: [{ value: "Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234567890 https://example.com/path?secret=1" }] }
  )`);
  await worker.run(`chrome.debugger.onEvent.emit(
    { tabId: 1 },
    "Network.requestWillBeSent",
    { requestId: "req-1", request: { url: "https://example.com/api?token=private", method: "POST", headers: { Authorization: "must-not-store" }, postData: "must-not-store" } }
  )`);
  await worker.run(`chrome.debugger.onEvent.emit(
    { tabId: 1 },
    "Network.responseReceived",
    { requestId: "req-1", response: { url: "https://example.com/api?token=private", status: 500 } }
  )`);
  const entries = await worker.run("diagnosticCaptures.get(1).entries");
  const serialized = JSON.stringify(entries);
  assert.match(serialized, /\[REDACTED\]/);
  assert.match(serialized, /https:\/\/example\.com\/path/);
  assert.match(serialized, /https:\/\/example\.com\/api/);
  assert.doesNotMatch(serialized, /secret=1|token=private|must-not-store|abcdefghijklmnopqrstuvwxyz1234567890/);
  assert.equal(entries.length, 2);
  await worker.run("stopDiagnosticCapture(1)");
  assert.deepEqual(worker.detachedTabs, [1]);
});

test("P2 diagnostic redaction covers structured short credentials and cookies", async () => {
  const worker = loadWorker();
  const raw = [
    '{"access_token":"short-access","refresh_token":"short-refresh"}',
    "password=hunter2&api_key=tiny-key",
    "Cookie: session=short-cookie; csrf=short-csrf",
    "access_token%3Dencoded-short%26next%3Dvisible",
    "Bearer short-bearer",
    "eyJhbGciOiJIUzI1NiJ9.e30.short-signature",
  ].join("\n");
  const redacted = await worker.run(`redactDiagnosticText(${JSON.stringify(raw)})`);

  assert.match(redacted, /access_token.*\[REDACTED\]/i);
  assert.match(redacted, /refresh_token.*\[REDACTED\]/i);
  assert.match(redacted, /Cookie=\[REDACTED\]/i);
  assert.match(redacted, /Bearer \[REDACTED\]/);
  assert.doesNotMatch(
    redacted,
    /short-access|short-refresh|hunter2|tiny-key|short-cookie|short-csrf|encoded-short|short-bearer|short-signature/
  );
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
  const media = context.WebBridgeMarkdown.toSafeHtml([
    "![result](output/chart.png)",
    "![external](https://example.com/chart.png)",
    "![blocked](data:image/png;base64,AAAA)",
    "![escape](../secret.png)",
  ].join("\n"));
  assert.match(media, /data-webbridge-media-src="output\/chart\.png"/);
  assert.match(media, /data-webbridge-remote-media-src="https:\/\/example\.com\/chart\.png"/);
  assert.doesNotMatch(media, /data:image/);
  assert.doesNotMatch(media, /\.\.\/secret/);
  assert.match(sidePanelSource, /URL\.createObjectURL/);
  assert.match(sidePanelSource, /URL\.revokeObjectURL/);
  assert.match(sidePanelSource, /await panelFetch\(path\)/);
  assert.match(sidePanelSource, /data-webbridge-remote-media-src/);
  assert.match(sidePanelSource, /referrerPolicy = "no-referrer"/);
  assert.match(sidePanelSource, /attachment\.deletable/);
  assert.match(sidePanelSource, /method: "DELETE"/);
});

test("P2 remote Markdown images do not create an image before user click", async () => {
  const start = sidePanelSource.indexOf("async function hydrateMarkdownMedia");
  const end = sidePanelSource.indexOf("\n}\n\nasync function renderAttachments", start) + 3;
  let clickHandler = null;
  let createdImages = 0;
  let authenticatedLoads = 0;
  const button = {
    dataset: {
      webbridgeRemoteMediaSrc: "https://remote.example/private.png",
      webbridgeRemoteMediaAlt: "External chart",
    },
    addEventListener(type, handler) {
      assert.equal(type, "click");
      clickHandler = handler;
    },
    replaceWith(value) {
      this.replacement = value;
    },
  };
  const root = {
    querySelectorAll(selector) {
      return selector.startsWith("img") ? [] : [button];
    },
  };
  const context = vm.createContext({
    document: {
      createElement(tag) {
        assert.equal(tag, "img");
        createdImages += 1;
        return {};
      },
    },
    panelMediaPath() { return ""; },
    async authenticatedMediaUrl() {
      authenticatedLoads += 1;
      return "blob:safe";
    },
  });
  vm.runInContext(
    `${sidePanelSource.slice(start, end)}\nglobalThis.runHydrate = hydrateMarkdownMedia;`,
    context,
    { filename: "sidepanel-media.js" }
  );

  await context.runHydrate(root);
  assert.equal(createdImages, 0);
  assert.equal(authenticatedLoads, 0);
  assert.equal(typeof clickHandler, "function");

  clickHandler();
  assert.equal(createdImages, 1);
  assert.equal(button.replacement.src, "https://remote.example/private.png");
  assert.equal(button.replacement.referrerPolicy, "no-referrer");
});

test("explicit selection submit creates and binds a browser session with provenance", async () => {
  let interactionBody = null;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/relay-ticket")) {
        return { ok: true, async json() { return { ticket: "ticket-once" }; } };
      }
      if (url.endsWith("/bindings")) {
        return { ok: true, async json() { return []; } };
      }
      if (url.endsWith("/bindings/1/sessions") && init.method === "POST") {
        return {
          ok: true,
          async json() {
            return {
              session: { id: "session-1", title: "Browser: Active" },
              binding: {
                tab_id: 1,
                session_id: "session-1",
                origin: "https://example.com",
              },
            };
          },
        };
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
    `submitBrowserContext(${JSON.stringify(tab)}, contextMenuPayload(${JSON.stringify(info)}, ${JSON.stringify(tab)}))`
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

test("context menu opens an editable Side Panel draft without submitting", async () => {
  let interactions = 0;
  const worker = loadWorker({
    fetchResponder: async (url) => {
      if (url.endsWith("/interactions")) interactions += 1;
      throw new Error(`Unexpected fetch ${url}`);
    },
  });
  await new Promise((resolve) => setImmediate(resolve));
  const result = await worker.run(`sendContextMenuInteraction(
    {
      menuItemId: "webbridge-ask-selection",
      pageUrl: "https://example.com/page?private=1",
      selectionText: "Selected context"
    },
    { id: 1, windowId: 10, title: "Example", url: "https://example.com/page?private=1" }
  )`);
  assert.equal(result.status, "draft");
  assert.equal(interactions, 0);
  assert.equal(worker.storedSession["webbridgePanelContextDraft:1"].payload.metadata.page_url, "https://example.com/page");
  assert.equal(worker.storedSession["webbridgePanelContextDraft:1"].payload.metadata.selection_text, "Selected context");
  assert.equal(
    worker.storedSession["webbridgePanelContextDraft:1"].page_instance_id,
    worker.storedSession["webbridgeTabPageInstance:1"]
  );
  assert.ok(worker.sidePanelCalls.some((call) => call.kind === "open" && call.options.tabId === 1));
  assert.match(sidePanelSource, /consumeContextMenuDraft/);
  assert.match(sidePanelSource, /review and send/);
});

test("context menu drafts are isolated by tab and page", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  await worker.run(`Promise.all([
    sendContextMenuInteraction(
      { menuItemId: "webbridge-ask-page", pageUrl: "https://example.com/one" },
      { id: 1, windowId: 10, title: "One", url: "https://example.com/one" }
    ),
    sendContextMenuInteraction(
      { menuItemId: "webbridge-ask-page", pageUrl: "https://example.com/two" },
      { id: 2, windowId: 10, title: "Two", url: "https://example.com/two" }
    )
  ])`);
  assert.equal(worker.storedSession["webbridgePanelContextDraft:1"].page_url, "https://example.com/one");
  assert.equal(worker.storedSession["webbridgePanelContextDraft:2"].page_url, "https://example.com/two");
  assert.match(sidePanelSource, /draft\.page_url !== currentPageUrl/);
});

test("context menu draft is invalidated when the tab reloads or returns to the same URL", async () => {
  const worker = loadWorker();
  await new Promise((resolve) => setImmediate(resolve));
  await worker.run(`sendContextMenuInteraction(
    { menuItemId: "webbridge-ask-page", pageUrl: "https://example.com/active" },
    { id: 1, windowId: 10, title: "Active", url: "https://example.com/active" }
  )`);
  const initialInstance = worker.storedSession["webbridgeTabPageInstance:1"];
  assert.ok(worker.storedSession["webbridgePanelContextDraft:1"]);

  await worker.run("rotateTabPageInstance(1)");

  assert.notEqual(worker.storedSession["webbridgeTabPageInstance:1"], initialInstance);
  assert.equal(worker.storedSession["webbridgePanelContextDraft:1"], undefined);
  assert.match(sidePanelSource, /draft\.page_instance_id !== stored\[pageInstanceKey\]/);
  assert.match(workerSource, /changeInfo\.status === "loading"/);
});

test("explicit browser context reuses its assigned session", async () => {
  let interactionBody = null;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
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
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/relay-ticket")) {
        return { ok: true, async json() { return { ticket: "ticket-once" }; } };
      }
      if (url.endsWith("/bindings") && !init.method) {
        return { ok: true, async json() { return []; } };
      }
      if (url.endsWith("/bindings/1/sessions") && init.method === "POST") {
        sessionCreates++;
        return {
          ok: true,
          async json() {
            return {
              session: { id: "session-1", title: "Browser: Active" },
              binding: {
                tab_id: 1,
                session_id: "session-1",
                origin: "https://example.com",
              },
            };
          },
        };
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
      relayBase: "ws://relay.example",
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

test("P1 browser context rejects restricted pages before any network request", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://relay.example",
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

test("P3 text watch matches without sending browser context until the user confirms", async () => {
  let interactionBody = null;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
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
  assert.ok(worker.scriptCalls.some((call) => call.files?.includes("text_watch.js")));
  assert.ok(worker.tabMessages.some((call) => call.message.type === "webbridge_text_watch" && call.message.enabled));
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
      relayBase: "ws://relay.example",
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
      relayBase: "ws://relay.example",
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
    storedConfig: { relayBase: "ws://relay.example" },
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

test("P3 multi-watch triage exposes matched send cancel and stop-all controls", () => {
  assert.match(sidePanelHtml, /id="watchList"/);
  assert.match(sidePanelHtml, /id="stopAllWatchesBtn"/);
  assert.match(sidePanelSource, /function renderWatchList/);
  assert.match(sidePanelSource, /send_matched_text_watch/);
  assert.match(sidePanelSource, /cancel_all_text_watches/);
  assert.match(workerSource, /async function cancelAllTextWatches/);
  assert.match(workerSource, /webbridge_text_watch_matched/);
  assert.match(sidePanelSource, /automation_state_changed/);
  assert.ok(fs.existsSync(path.join(__dirname, "..", "extensions", "webbridge", "text_watch.js")));
});

test("P2 automation UI explains user goals and syncs live state to Desktop", () => {
  assert.match(sidePanelHtml, /What should EvoFlux help with\?/);
  assert.match(sidePanelHtml, /Wait for something on this page/);
  assert.match(sidePanelHtml, /Teach EvoFlux a repeatable task/);
  assert.match(sidePanelHtml, /Help diagnose this page/);
  assert.match(sidePanelHtml, /Browser control/);
  assert.doesNotMatch(sidePanelHtml, /<h2>Page automation<\/h2>/i);
  assert.match(workerSource, /event: "automation_state"/);
  assert.match(workerSource, /async function automationStateSnapshot/);
  assert.match(workerSource, /notifyAutomationState\("browser_control"/);
});

test("P2 automation state frame contains summaries but no captured diagnostics", async () => {
  const worker = loadWorker({
    storedConfig: {
      webbridgeTextWatches: [{
        id: "watch-sync",
        tab_id: 1,
        origin: "https://example.com",
        page_url: "https://example.com/active",
        session_id: "session-1",
        needle: "Build complete",
        state: "armed",
        created_at: Date.now(),
        expires_at: Date.now() + 60_000,
        matched_at: null,
      }],
    },
  });
  const frameJson = await worker.run(`(async () => {
    const frames = [];
    ws = { readyState: WebSocket.OPEN, send: (value) => frames.push(value) };
    await broadcastAutomationState();
    return frames[0];
  })()`);
  const frame = JSON.parse(frameJson);
  assert.equal(frame.type, "event");
  assert.equal(frame.event, "automation_state");
  assert.equal(frame.data.text_watches[0].needle, "Build complete");
  assert.deepEqual(frame.data.agent_control_tab_ids, []);
  assert.equal(Object.hasOwn(frame.data, "diagnostic_entries"), false);
});

test("P3 real-time text watch accepts only the armed tab and page", async () => {
  const worker = loadWorker({
    storedConfig: {
      webbridgeTextWatches: [{
        id: "watch-live",
        tab_id: 1,
        origin: "https://example.com",
        page_url: "https://example.com/active",
        session_id: "session-1",
        needle: "Build complete",
        state: "armed",
        created_at: Date.now(),
        expires_at: Date.now() + 60_000,
        matched_at: null,
      }],
    },
  });

  const stale = await worker.run(`markTextWatchMatched(
    "watch-live",
    { id: 1, url: "https://example.com/other" },
    "https://example.com/other"
  )`);
  assert.equal(stale, null);
  assert.equal(worker.storedConfig.webbridgeTextWatches[0].state, "armed");

  const matched = await worker.run(`markTextWatchMatched(
    "watch-live",
    { id: 1, url: "https://example.com/active" },
    "https://example.com/active"
  )`);
  assert.equal(matched.state, "matched");
  assert.equal(worker.storedConfig.webbridgeTextWatches[0].state, "matched");
  assert.ok(worker.actionCalls.some((call) => call.kind === "badge" && call.options.text === "W"));
});

test("P3 page-local text observer reports a case-insensitive match without page content", async () => {
  const runtime = loadTextWatchRuntime();
  runtime.context.__evofluxTextWatchRuntime.start({
    id: "watch-runtime",
    needle: "Build Complete",
  });
  assert.equal(runtime.sent.length, 0);

  runtime.body.innerText = "Deployment status: BUILD COMPLETE for private customer alpha";
  runtime.context.__evofluxTextWatchRuntime.check();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(Object.keys(runtime.sent[0]).sort(), ["page_url", "type", "watch_id"]);
  assert.equal(runtime.sent[0].watch_id, "watch-runtime");
  assert.equal(JSON.stringify(runtime.sent).includes("private customer alpha"), false);
});

test("P3 Teach Mode redacts secrets and saves a pairing-scoped semantic draft", async () => {
  let draftBody = null;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
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

test("P2 release browser control persists until the user resumes the agent", async () => {
  const worker = loadWorker();
  await worker.run("ensureDebuggerAttached(1)");

  const result = await worker.run("releaseBrowserControlToHuman(1)");

  assert.equal(result.released, true);
  assert.equal(result.lease.tab_id, 1);
  assert.deepEqual(worker.detachedTabs, [1]);
  assert.equal(worker.run("attachedTabs.has(1)"), false);
  assert.equal(worker.storedSession.webbridgeHumanControlLease[1].tab_id, 1);
  await assert.rejects(worker.run("resolveTab({ tab_id: 1 })"), /Human control is active/);
  assert.match(sidePanelSource, /release_browser_control/);
  assert.match(sidePanelSource, /Resume agent control/);
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
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
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
  assert.equal(worker.fetchCalls[0].url, "http://127.0.0.1:4082/api/team/webbridge/relay-ticket");
  assert.equal(worker.fetchCalls[0].init.headers.Authorization, "Bearer pair-secret");
  assert.equal(worker.sockets.length, 1);
  assert.equal(
    worker.sockets[0].url,
    "ws://127.0.0.1:4082/api/team/webbridge/relay?_ticket=ticket-once"
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

test("disconnect supersedes an in-flight relay ticket request", async () => {
  let resolveTicket;
  const pendingTicket = new Promise((resolve) => { resolveTicket = resolve; });
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "pair-secret",
      pairingId: "pairing-1",
      pairingRelayBase: "ws://127.0.0.1:4082",
    },
    fetchResponder: async () => pendingTicket,
  });
  await new Promise((resolve) => setImmediate(resolve));

  worker.run("disconnect()");
  resolveTicket({ ok: true, async json() { return { ticket: "stale-ticket" }; } });
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.sockets.length, 0);
  assert.equal(worker.run("manualDisconnect"), true);
  assert.equal(worker.run("connectInFlight"), false);
});

test("missing Native Messaging host never falls back to unauthenticated local pairing", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      accessToken: "legacy-secret",
    },
    fetchResponder: async (url) => { throw new Error(`Unexpected fetch ${url}`); },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.fetchCalls.length, 0);
  assert.equal(worker.sockets.length, 0);
  assert.equal(worker.storedConfig.accessToken, undefined);
  assert.equal(worker.run("lastCloseReason"), "native");
  assert.match(worker.run("nativeDiscoveryError"), /host not found/i);
});

test("Native Messaging discovers the desktop sidecar and pairs without a pasted URL", async () => {
  const discoveryToken = "native-discovery-token-that-is-long-enough";
  const worker = loadWorker({
    nativeMessageResponder(host, message, callback) {
      assert.equal(host, "com.evoflux.webbridge");
      assert.equal(message.type, "discover");
      callback({
        ok: true,
        protocol_version: 1,
        app_pid: 4242,
        base_url: "http://127.0.0.1:43123",
        discovery_token: discoveryToken,
      });
    },
    fetchResponder: async (url, init) => {
      if (url.endsWith("/pairing/native")) {
        const body = JSON.parse(init.body);
        assert.equal(body.discovery_token, discoveryToken);
        assert.equal(init.headers.Authorization, undefined);
        return {
          ok: true,
          async json() {
            return {
              pairing_id: "pairing-native",
              credential: "native-scoped-secret",
              scopes: ["relay"],
            };
          },
        };
      }
      if (url.endsWith("/relay-ticket")) {
        assert.equal(init.headers.Authorization, "Bearer native-scoped-secret");
        return { ok: true, async json() { return { ticket: "native-ticket" }; } };
      }
      throw new Error(`Unexpected fetch ${url}`);
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(
    worker.fetchCalls.map((call) => new URL(call.url).pathname),
    ["/api/team/webbridge/pairing/native", "/api/team/webbridge/relay-ticket"],
  );
  assert.equal(worker.storedConfig.relayBase, "ws://127.0.0.1:43123");
  assert.equal(worker.storedConfig.pairingTransport, "native");
  assert.equal(worker.storedConfig.discoveryToken, undefined);
  assert.equal(worker.sockets[0].url, "ws://127.0.0.1:43123/api/team/webbridge/relay?_ticket=native-ticket");
  assert.equal(worker.run("connectionMode"), "native");
});

test("Native Messaging carries a scoped pairing across sidecar port changes", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:41000",
      pairingCredential: "existing-native-secret",
      pairingId: "pairing-native",
      pairingRelayBase: "ws://127.0.0.1:41000",
      pairingTransport: "native",
    },
    nativeMessageResponder(_host, _message, callback) {
      callback({
        ok: true,
        protocol_version: 1,
        app_pid: 4243,
        base_url: "http://127.0.0.1:42000",
        discovery_token: "replacement-discovery-token-long-enough",
      });
    },
    fetchResponder: async (url, init) => {
      assert.equal(url, "http://127.0.0.1:42000/api/team/webbridge/relay-ticket");
      assert.equal(init.headers.Authorization, "Bearer existing-native-secret");
      return { ok: true, async json() { return { ticket: "replacement-ticket" }; } };
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.fetchCalls.length, 1);
  assert.equal(worker.storedConfig.pairingRelayBase, "ws://127.0.0.1:42000");
  assert.equal(worker.sockets[0].url, "ws://127.0.0.1:42000/api/team/webbridge/relay?_ticket=replacement-ticket");
});

test("Native Messaging heartbeat reconnects when desktop changes endpoint", async () => {
  let nativePort = 41000;
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:41000",
      pairingCredential: "existing-native-secret",
      pairingId: "pairing-native",
      pairingRelayBase: "ws://127.0.0.1:41000",
      pairingTransport: "native",
    },
    nativeMessageResponder(_host, _message, callback) {
      callback({
        ok: true,
        protocol_version: 1,
        app_pid: 4244,
        base_url: `http://127.0.0.1:${nativePort}`,
        discovery_token: "heartbeat-discovery-token-long-enough",
      });
    },
    fetchResponder: async (url) => {
      assert.equal(url, "http://127.0.0.1:41000/api/team/webbridge/relay-ticket");
      return { ok: true, async json() { return { ticket: "initial-ticket" }; } };
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const firstSocket = worker.sockets[0];
  firstSocket.readyState = worker.context.WebSocket.OPEN;
  firstSocket.onopen();

  nativePort = 42000;
  assert.equal(await worker.run("refreshNativeConnectionIfChanged()"), true);

  assert.equal(firstSocket.readyState, worker.context.WebSocket.CLOSED);
  assert.equal(worker.storedConfig.relayBase, "ws://127.0.0.1:42000");
  assert.equal(worker.storedConfig.pairingRelayBase, "ws://127.0.0.1:42000");
  assert.equal(worker.run("lastCloseReason"), "endpoint_changed");
  assert.equal(worker.nativeMessageCalls.length, 2);
});

test("revoked pairing credential is removed before reconnect", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "revoked-secret",
      pairingId: "pairing-revoked",
      pairingRelayBase: "ws://127.0.0.1:4082",
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
  assert.equal(worker.run("manualDisconnect"), false);
});

test("relay revocation close clears pairing without reconnect", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "paired-secret",
      pairingId: "pairing-active",
      pairingRelayBase: "ws://127.0.0.1:4082",
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
  assert.equal(worker.run("manualDisconnect"), false);
  assert.equal(worker.sockets.length, 1);
});

test("native discovery replaces a relay-bound credential without sending the old credential", async () => {
  const worker = loadWorker({
    storedConfig: {
      relayBase: "ws://127.0.0.1:4082",
      pairingCredential: "relay-bound-secret",
      pairingId: "pairing-bound",
      pairingRelayBase: "wss://original.example",
    },
    fetchResponder: async (url, init) => {
      assert.notEqual(init.headers?.Authorization, "Bearer relay-bound-secret");
      if (url.endsWith("/pairing/native")) {
        assert.equal(JSON.parse(init.body).discovery_token, "default-native-discovery-token-long-enough");
        return {
          ok: true,
          async json() {
            return { pairing_id: "pairing-new", credential: "new-secret", scopes: ["relay"] };
          },
        };
      }
      if (url.endsWith("/relay-ticket")) {
        assert.equal(init.headers.Authorization, "Bearer new-secret");
        return { ok: true, async json() { return { ticket: "new-ticket" }; } };
      }
      throw new Error(`Unexpected fetch ${url}`);
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(worker.fetchCalls.length, 2);
  assert.equal(worker.sockets.length, 1);
  assert.equal(worker.storedConfig.pairingCredential, "new-secret");
  assert.equal(worker.storedConfig.pairingRelayBase, "ws://127.0.0.1:4082");
});

test("manual remote relay cannot bypass required Native Messaging discovery", async () => {
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
  assert.equal(worker.run("lastCloseReason"), "native");
  assert.equal(worker.run("manualDisconnect"), false);
});

test("middle click is preserved in both CDP events", async () => {
  const worker = loadWorker();

  const result = await worker.run('cmdClick({ x: 10, y: 20, button: "middle" })');

  assert.equal(result.button, "middle");
  const mouseCalls = worker.cdpCalls.filter((call) => call.method === "Input.dispatchMouseEvent");
  const clickCalls = mouseCalls.filter((call) => ["mousePressed", "mouseReleased"].includes(call.params.type));
  assert.deepEqual(clickCalls.map((call) => call.params.button), ["middle", "middle"]);
});

test("agent control mirrors CDP pointer events and releases the visual overlay", async () => {
  const worker = loadWorker({
    tabMessageResponder(_tabId, message) {
      return {
        ok: true,
        pointer: message.enabled && !message.pointer ? { x: 80, y: 90 } : undefined,
      };
    },
  });

  await worker.run('cmdClick({ x: 18, y: 27, button: "left" })');

  assert.ok(worker.scriptCalls.some((call) => call.files?.includes("agent_control_overlay.js")));
  const controlMessages = worker.tabMessages
    .filter((call) => call.message.type === "webbridge_agent_control")
    .map((call) => call.message);
  assert.equal(controlMessages[0].enabled, true);
  const pointerMessages = controlMessages.filter((message) => message.pointer);
  const pointerPhases = pointerMessages.map((message) => message.pointer.phase);
  assert.ok(pointerPhases.filter((phase) => phase === "move").length >= 3);
  assert.deepEqual(pointerPhases.slice(-2), ["press", "release"]);
  assert.deepEqual(
    pointerMessages.slice(-2).map((message) => [message.pointer.x, message.pointer.y]),
    [[18, 27], [18, 27]]
  );
  const mouseMoves = worker.cdpCalls
    .filter((call) => call.method === "Input.dispatchMouseEvent" && call.params.type === "mouseMoved")
    .map((call) => call.params);
  assert.ok(mouseMoves.length >= 3);
  assert.deepEqual([mouseMoves.at(-1).x, mouseMoves.at(-1).y], [18, 27]);
  assert.ok(mouseMoves.some((point) => {
    const lineCrossProduct = (point.x - 80) * (27 - 90) - (point.y - 90) * (18 - 80);
    return Math.abs(lineCrossProduct) > 1;
  }));

  await worker.run("detachAllDebuggers()");
  assert.equal(worker.tabMessages.at(-1).message.enabled, false);
  assert.match(agentControlOverlaySource, /pointer-events:none/);
  assert.match(agentControlOverlaySource, /prefers-reduced-motion: reduce/);
  assert.match(agentControlOverlaySource, /EvoFlux control/);
  assert.match(agentControlOverlaySource, /class="cursor-aura"/);
  assert.match(agentControlOverlaySource, /id="evoflux-cursor-fill"/);
  assert.match(agentControlOverlaySource, /drop-shadow\(0 0 3px rgba\(72, 202, 224, \.42\)\)/);
  assert.match(agentControlOverlaySource, /stop-color="#020405"/);
  assert.match(agentControlOverlaySource, /stroke: rgba\(255, 255, 255, \.96\)/);
  assert.doesNotMatch(agentControlOverlaySource, /117, 76, 255/);
  assert.doesNotMatch(agentControlOverlaySource, /#(?:8d68ff|b65cff)|101, 86, 255|124, 88, 255/);
  assert.match(agentControlOverlaySource, /@keyframes evoflux-frame-wave/);
  assert.doesNotMatch(agentControlOverlaySource, /evoflux-edge-flow|class="edge /);
  assert.doesNotMatch(agentControlOverlaySource, /class="cursor-glow"/);
  assert.match(agentControlOverlaySource, /function setSuspended/);
  assert.match(agentControlOverlaySource, /host\.style\.visibility = suspended \? "hidden" : "visible"/);
  assert.match(agentControlOverlaySource, /transition: transform 28ms linear/);
  assert.match(agentControlOverlaySource, /pointer: lastX == null/);
});

test("screenshots suspend and restore the take-control overlay", async () => {
  const worker = loadWorker();
  await worker.run("ensureDebuggerAttached(1)");
  worker.tabMessages.length = 0;
  worker.setCdpResponder((method) => {
    if (method === "Runtime.evaluate") {
      return {
        result: {
          value: {
            width: 1280,
            height: 720,
            dpr: 2,
            scrollX: 0,
            scrollY: 0,
            pageWidth: 1280,
            pageHeight: 2400,
          },
        },
      };
    }
    if (method === "Page.captureScreenshot") return { data: "clean-png" };
    return {};
  });

  const result = await worker.run("cmdScreenshot({})");

  assert.equal(result.data, "clean-png");
  assert.deepEqual(
    worker.tabMessages
      .filter((call) => typeof call.message.suspended === "boolean")
      .map((call) => call.message.suspended),
    [true, false]
  );
  assert.equal(worker.run("agentControlOverlays.has(1)"), true);
  assert.equal(worker.run("overlayCaptureSuspensions.has(1)"), false);
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
