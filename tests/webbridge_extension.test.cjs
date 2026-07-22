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

function loadWorker() {
  const cdpCalls = [];
  const detachedTabs = [];
  const sockets = [];
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
          return { extensionId: "ext-test" };
        },
        async set() {},
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
    navigator: { userAgent: "Chrome/140" },
    WebSocket: FakeWebSocket,
    clearTimeout,
    setTimeout,
  });
  vm.runInContext(workerSource, context, { filename: "background.js" });

  return {
    cdpCalls,
    context,
    detachedTabs,
    run(expression) {
      return vm.runInContext(expression, context);
    },
    setCdpResponder(responder) {
      cdpResponder = responder;
    },
  };
}

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