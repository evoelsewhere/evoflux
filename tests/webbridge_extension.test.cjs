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
  const storedConfig = {
    extensionId: "ext-test",
    ...(options.storedConfig || {}),
  };
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
  };
  const tabs = {
    onRemoved: eventChannel(),
    onUpdated: eventChannel(),
    onActivated: eventChannel(),
    onCreated: eventChannel(),
    onMoved: eventChannel(),
    async query(queryInfo = {}) {
      if (queryInfo.active) return tabList.filter((tab) => tab.active);
      return tabList;
    },
    async get(tabId) {
      const tab = tabList.find((candidate) => candidate.id === tabId);
      if (!tab) throw new Error(`No tab ${tabId}`);
      return tab;
    },
    async update(tabId, changes) {
      const tab = await this.get(tabId);
      Object.assign(tab, changes);
      return tab;
    },
    async create({ url, active }) {
      const tab = { id: 3, windowId: 10, active, pinned: false, title: "", url };
      tabList.push(tab);
      return tab;
    },
    async remove(tabId) {
      const index = tabList.findIndex((tab) => tab.id === tabId);
      if (index >= 0) tabList.splice(index, 1);
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
      },
    },
    alarms: {
      create() {},
      onAlarm: eventChannel(),
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
    sockets,
    storedConfig,
    run(expression) {
      return vm.runInContext(expression, context);
    },
    setCdpResponder(responder) {
      cdpResponder = responder;
    },
  };
}

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
  assert.deepEqual(register.capabilities.interactions, ["context.share"]);
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
  assert.equal(worker.storedConfig.accessToken, "");
  assert.equal(result.pairing_id, "pairing-2");
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