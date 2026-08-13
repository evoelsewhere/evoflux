"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "transcript-follow.js"),
  "utf8",
);

class FakeClassList {
  constructor() { this.values = new Set(); }
  toggle(name, force) {
    if (force) this.values.add(name); else this.values.delete(name);
  }
  contains(name) { return this.values.has(name); }
}

class FakeElement {
  constructor() {
    this.listeners = new Map();
    this.classList = new FakeClassList();
    this.scrollHeight = 1_000;
    this.clientHeight = 200;
    this.scrollTop = 800;
    this.offsetWidth = 300;
  }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  emit(type, event = {}) { this.listeners.get(type)?.({ target: this, ...event }); }
  closest() { return null; }
  getBoundingClientRect() { return { right: 300 }; }
}

function loadController() {
  let nextFrame = 0;
  const frames = new Map();
  const context = vm.createContext({
    Element: FakeElement,
    document: { documentElement: { dataset: { motion: "reduced" } } },
    requestAnimationFrame(callback) {
      const id = ++nextFrame;
      frames.set(id, callback);
      return id;
    },
    cancelAnimationFrame(id) { frames.delete(id); },
  });
  vm.runInContext(source, context, { filename: "transcript-follow.js" });
  const flushFrames = () => {
    for (const [id, callback] of [...frames]) {
      frames.delete(id);
      callback(16);
    }
  };
  return { context, flushFrames };
}

test("layout scroll keeps a pinned transcript following while explicit upward intent detaches", () => {
  const { context, flushFrames } = loadController();
  const element = new FakeElement();
  const latestButton = new FakeElement();
  const controller = context.WebBridgeTranscriptFollow.create({ element, latestButton });

  element.scrollTop = 620;
  element.emit("scroll");
  flushFrames();
  flushFrames();
  assert.equal(controller.pinned, true);
  assert.equal(element.scrollTop, 800);
  assert.equal(latestButton.classList.contains("visible"), false);

  element.emit("wheel", { deltaY: -12 });
  assert.equal(controller.pinned, false);
  assert.equal(latestButton.classList.contains("visible"), true);

  element.scrollHeight = 1_200;
  controller.follow();
  flushFrames();
  assert.equal(element.scrollTop, 800);

  element.scrollTop = 700;
  element.emit("scroll");
  flushFrames();
  element.scrollTop = 1_000;
  element.emit("scroll");
  flushFrames();
  assert.equal(controller.pinned, true);
  assert.equal(latestButton.classList.contains("visible"), false);
});

test("Back to latest reattaches immediately and smooth following remains monotonic", () => {
  const { context } = loadController();
  const element = new FakeElement();
  const latestButton = new FakeElement();
  const controller = context.WebBridgeTranscriptFollow.create({ element, latestButton });
  controller.detach();
  element.scrollTop = 300;
  latestButton.emit("click");
  assert.equal(controller.pinned, true);
  assert.equal(element.scrollTop, element.scrollHeight);

  const next = context.WebBridgeTranscriptFollow.nextScrollTop(100, 500, 16);
  assert.ok(next > 100 && next < 500);
  assert.equal(context.WebBridgeTranscriptFollow.nextScrollTop(500, 300, 16), 300);
});
