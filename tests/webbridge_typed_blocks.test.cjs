"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "chat-renderer.js"),
  "utf8",
);

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  contains(name) { return this.values.has(name); }
  toggle(name, force) {
    const next = force === undefined ? !this.values.has(name) : Boolean(force);
    if (next) this.values.add(name); else this.values.delete(name);
    return next;
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.classList = new FakeClassList();
    this.dataset = {};
    this.attributes = {};
    this.hidden = false;
    this.textContent = "";
    this.innerHTML = "";
  }
  set className(value) {
    this._className = value;
    this.classList = new FakeClassList();
    String(value).split(/\s+/).filter(Boolean).forEach((name) => this.classList.add(name));
  }
  get className() { return this._className || ""; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  closest() { return null; }
  remove() { this.removed = true; }
}

function loadRenderer(globals = {}) {
  const frames = new Map();
  let frameId = 0;
  const context = vm.createContext({
    document: { createElement: (tag) => new FakeElement(tag) },
    requestAnimationFrame(callback) {
      const id = ++frameId;
      frames.set(id, callback);
      return id;
    },
    cancelAnimationFrame(id) { frames.delete(id); },
    setTimeout,
    clearTimeout,
    ...globals,
  });
  vm.runInContext(source, context, { filename: "chat-renderer.js" });
  return {
    context,
    flushFrames() {
      for (const [id, callback] of [...frames]) {
        frames.delete(id);
        callback(16);
      }
    },
  };
}

class FakeWidgetElement {
  constructor(tagName, attributes = {}, content = "") {
    this.tagName = tagName.toUpperCase();
    this.attributes = Object.entries(attributes).map(([name, value]) => ({ name, value }));
    this.content = content;
    this.removed = false;
  }
  remove() { this.removed = true; }
  removeAttribute(name) {
    this.attributes = this.attributes.filter((attribute) => attribute.name !== name);
  }
  serialize() {
    const attributes = this.attributes
      .map(({ name, value }) => ` ${name}="${value}"`)
      .join("");
    return `<${this.tagName.toLowerCase()}${attributes}>${this.content}</${this.tagName.toLowerCase()}>`;
  }
}

class FakeWidgetDOMParser {
  parseFromString() {
    const blocked = [
      new FakeWidgetElement("script", {}, "alert(1)"),
      new FakeWidgetElement("iframe", { src: "https://evil.test" }),
      new FakeWidgetElement("object", { data: "https://evil.test" }),
      new FakeWidgetElement("embed", { src: "https://evil.test" }),
      new FakeWidgetElement("meta", { "http-equiv": "refresh", content: "0;url=https://evil.test" }),
      new FakeWidgetElement("base", { href: "https://evil.test" }),
      new FakeWidgetElement("link", { rel: "stylesheet", href: "https://evil.test" }),
      new FakeWidgetElement("form", { action: "https://evil.test" }),
    ];
    const allowed = [
      new FakeWidgetElement("img", {
        src: "data:image/png;base64,iVBORw0KGgo=",
        srcset: "https://evil.test/tracker.png 2x",
        onerror: "alert(1)",
      }),
      new FakeWidgetElement("img", { src: "https://evil.test/tracker.png" }),
      new FakeWidgetElement("a", {
        href: "https://evil.test",
        target: "_top",
        onclick: "top.location='https://evil.test'",
      }, "Safe visual"),
      new FakeWidgetElement("div", { class: "chart", style: "color:red" }, "Chart"),
    ];
    const all = [...blocked, ...allowed];
    return {
      body: {
        querySelectorAll(selector) {
          return selector === "*" ? all.filter((element) => !element.removed) : blocked;
        },
        get innerHTML() {
          return all.filter((element) => !element.removed).map((element) => element.serialize()).join("");
        },
      },
    };
  }
}

test("typed renderer preserves text → tool → text chronology with live output", () => {
  const { context } = loadRenderer();
  const root = new FakeElement("div");
  const item = new FakeElement("article");
  item.classList.add("live", "live-turn");
  const renderer = context.WebBridgeTypedBlocks.create({
    createTurn() { return { item, content: root }; },
    textChanged(block) { block.content.textContent = block.rawContent; },
  });

  renderer.appendText({ agent: "Lead", text: "Before" });
  renderer.toolCall({ agent: "Lead", name: "shell", tool_call_id: "tool-1" });
  renderer.toolStart({ agent: "Lead", name: "shell", tool_call_id: "tool-1", arguments: "{\"command\":\"echo ok\"}" });
  renderer.toolOutput({ agent: "Lead", name: "shell", tool_call_id: "tool-1", text: "ok\n", stream: "stdout" });
  renderer.toolEnd({ agent: "Lead", name: "shell", tool_call_id: "tool-1", result: "exit 0", duration_ms: 25 });
  renderer.appendText({ agent: "Lead", text: "After" });

  assert.deepEqual(
    JSON.parse(JSON.stringify(renderer.turn.blocks.map((block) => block.type))),
    ["text", "tool", "text"],
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(renderer.turn.segments.map((segment) => segment.kind))),
    ["content", "activity", "content"],
  );
  assert.equal(renderer.turn.blocks[0].rawContent, "Before");
  assert.equal(renderer.turn.blocks[1].argumentsBody.textContent, '{\n  "command": "echo ok"\n}');
  assert.equal(renderer.turn.blocks[1].outputBody.textContent, "ok\n");
  assert.equal(renderer.turn.blocks[1].resultBody.textContent, "exit 0");
  assert.equal(renderer.turn.blocks[2].rawContent, "After");
  renderer.finish();
  assert.equal(item.classList.contains("live"), false);
});

test("live activity grouping stays stable and preserves the reader collapse choice", () => {
  const { context } = loadRenderer();
  const root = new FakeElement("div");
  const renderer = context.WebBridgeTypedBlocks.create({
    createTurn() { return { item: new FakeElement("article"), content: root }; },
  });

  renderer.appendThinking({ agent: "Lead", chars: 10 });
  const firstSegment = renderer.turn.segments[0];
  const firstElement = firstSegment.element;
  assert.equal(firstSegment.kind, "activity");
  assert.equal(firstElement.open, true);
  firstElement.open = false;

  renderer.toolCall({ agent: "Lead", name: "read_file", tool_call_id: "tool-1" });
  renderer.toolEnd({ agent: "Lead", name: "read_file", tool_call_id: "tool-1" });
  assert.equal(renderer.turn.segments[0], firstSegment);
  assert.equal(firstSegment.element, firstElement);
  assert.equal(firstSegment.blocks.length, 2);
  assert.equal(firstElement.open, false);
  assert.equal(firstSegment.label.textContent, "Read files");

  renderer.appendText({ agent: "Lead", text: "Checkpoint" });
  renderer.toolCall({ agent: "Lead", name: "shell", tool_call_id: "tool-2" });
  assert.deepEqual(
    JSON.parse(JSON.stringify(renderer.turn.segments.map((segment) => segment.kind))),
    ["activity", "content", "activity"],
  );
  assert.notEqual(renderer.turn.segments[2].element, firstElement);
});

test("Desktop parity keeps usage invisible and presents skill activity as inline rows", () => {
  const { context } = loadRenderer();
  const root = new FakeElement("div");
  const renderer = context.WebBridgeTypedBlocks.create({
    createTurn() { return { item: new FakeElement("article"), content: root }; },
  });

  renderer.appendThinking({ agent: "Lead", chars: 39 });
  assert.equal(renderer.appendEvent("usage", { total_tokens: 100 }), null);
  renderer.toolCall({
    agent: "Lead",
    name: "skill",
    tool_call_id: "skill-1",
    skill_action: "load",
    skill_name: "pptx",
  });
  renderer.toolEnd({
    agent: "Lead",
    name: "skill",
    tool_call_id: "skill-1",
    duration_ms: 43,
  });
  renderer.toolCall({ agent: "Lead", name: "load_tool", tool_call_id: "load-1" });
  renderer.toolEnd({ agent: "Lead", name: "load_tool", tool_call_id: "load-1", duration_ms: 16 });
  renderer.finish();

  assert.equal(renderer.turn.segments.length, 1);
  assert.equal(renderer.turn.segments[0].label.textContent, "Loaded a skill, used tools");
  assert.equal(renderer.turn.blocks[0].label.textContent, "Thought · 39 chars");
  assert.equal(renderer.turn.blocks[1].label.textContent, "Loaded skill");
  assert.equal(renderer.turn.blocks[1].header.textContent, "pptx");
  assert.equal(renderer.turn.blocks[1].duration.textContent, "43ms");
  assert.equal(renderer.turn.blocks[2].label.textContent, "Load Tool");
  assert.equal(renderer.turn.blocks[2].duration.textContent, "16ms");
});

test("sanitized webbridge arguments populate the Desktop-style tool inspector", () => {
  const { context } = loadRenderer();
  const renderer = context.WebBridgeTypedBlocks.create({
    createTurn() {
      return { item: new FakeElement("article"), content: new FakeElement("div") };
    },
  });

  renderer.toolStart({
    agent: "Lead",
    name: "webbridge",
    tool_call_id: "browser-1",
    display_arguments: {
      actions: [{ action: "status" }, { action: "get_tabs" }],
    },
  });
  renderer.toolEnd({
    agent: "Lead",
    name: "webbridge",
    tool_call_id: "browser-1",
    duration_ms: 97,
  });

  const block = renderer.turn.blocks[0];
  assert.equal(block.label.textContent, "Browsed");
  assert.equal(block.duration.textContent, "97ms");
  assert.equal(block.argumentsSection.hidden, false);
  assert.equal(
    block.argumentsBody.textContent,
    '{\n  "actions": [\n    {\n      "action": "status"\n    },\n    {\n      "action": "get_tabs"\n    }\n  ]\n}',
  );
});

test("reasoning and tool payloads remain text-safe while widgets are sandboxed", () => {
  const { context, flushFrames } = loadRenderer({ DOMParser: FakeWidgetDOMParser });
  const root = new FakeElement("div");
  const renderer = context.WebBridgeTypedBlocks.create({
    createTurn() { return { item: new FakeElement("article"), content: root }; },
    renderMarkdown(target, markdown) { target.textContent = markdown; },
  });

  renderer.appendThinking({ agent: "Lead", text: "<img src=x onerror=alert(1)>" });
  renderer.toolStart({ agent: "Lead", name: "read", tool_call_id: "tool-2", arguments: "<script>alert(1)</script>" });
  const widget = renderer.appendWidget({
    agent: "Lead",
    tool_call_id: "widget-1",
    html: "<script>top.location='https://evil.test'</script><b>Safe visual</b>",
    is_final: true,
  });
  flushFrames();

  assert.equal(renderer.turn.blocks[0].body.textContent, "<img src=x onerror=alert(1)>");
  assert.equal(renderer.turn.blocks[1].argumentsBody.textContent, "<script>alert(1)</script>");
  assert.equal(widget.iframe.attributes.sandbox, "");
  assert.match(widget.iframe.srcdoc, /default-src 'none'/);
  assert.match(widget.iframe.srcdoc, /form-action 'none'/);
  assert.match(widget.iframe.srcdoc, /navigate-to 'none'/);
  assert.match(widget.iframe.srcdoc, /Safe visual/);
});

test("widget sanitization fails closed when DOMParser is unavailable", () => {
  const { context } = loadRenderer();

  assert.equal(
    context.WebBridgeTypedBlocks.sanitizeWidgetHtml("<b>Unparsed widget</b>"),
    "",
  );
  assert.doesNotMatch(
    context.WebBridgeTypedBlocks.widgetDocument("<b>Unparsed widget</b>"),
    /Unparsed widget/,
  );
});

test("widget documents strip active markup and navigation attributes before srcdoc", () => {
  const { context } = loadRenderer({ DOMParser: FakeWidgetDOMParser });
  const sanitized = context.WebBridgeTypedBlocks.sanitizeWidgetHtml("<untrusted-widget>");
  const documentHtml = context.WebBridgeTypedBlocks.widgetDocument("<untrusted-widget>");

  assert.doesNotMatch(sanitized, /<(?:script|iframe|object|embed|meta|base|link|form)\b/i);
  assert.doesNotMatch(sanitized, /\sonerror=/i);
  assert.doesNotMatch(sanitized, /\ssrcset=/i);
  assert.doesNotMatch(sanitized, /https:\/\/evil\.test/i);
  assert.match(sanitized, /src="data:image\/png;base64,iVBORw0KGgo="/);
  assert.match(sanitized, /class="chart" style="color:red"/);
  assert.match(sanitized, /Safe visual/);
  assert.match(documentHtml, /default-src 'none'/);
  assert.match(documentHtml, /form-action 'none'/);
  assert.match(documentHtml, /navigate-to 'none'/);
});

test("redacted thinking and tool deltas show Desktop-only progress without raw-data placeholders", () => {
  const { context } = loadRenderer();
  const root = new FakeElement("div");
  const renderer = context.WebBridgeTypedBlocks.create({
    createTurn() { return { item: new FakeElement("article"), content: root }; },
    textChanged(block) { block.content.textContent = block.rawContent; },
  });

  renderer.appendThinking({ agent: "Lead", chars: 1_200 });
  renderer.appendThinking({ agent: "Lead", chars: 34 });
  renderer.toolOutput({
    agent: "Lead",
    name: "shell",
    tool_call_id: "tool-redacted",
    chars: 500,
    redacted: true,
    stream: "stdout",
  });
  renderer.toolOutput({
    agent: "Lead",
    name: "shell",
    tool_call_id: "tool-redacted",
    chars: 25,
    redacted: true,
    stream: "stdout",
  });
  renderer.appendText({ agent: "Lead", text: "Finished" });

  assert.deepEqual(
    JSON.parse(JSON.stringify(renderer.turn.blocks.map((block) => block.type))),
    ["thinking", "tool", "text"],
  );
  const thinking = renderer.turn.blocks[0];
  assert.equal(thinking.label.textContent, "Thinking · 1,234 chars");
  assert.equal(thinking.body.textContent, "Reasoning remains in EvoFlux Desktop.");
  assert.equal(thinking.body.dataset.desktopOnly, "reasoning");
  assert.equal(thinking.rawContent, "");

  const tool = renderer.turn.blocks[1];
  assert.equal(tool.duration.textContent, "Running · 525 chars");
  assert.equal(tool.outputBody.textContent, "525 chars received\nFull output available in EvoFlux Desktop");
  assert.equal(tool.outputSection.dataset.desktopOnly, "tool-output");
  assert.equal(tool.output, "");
  assert.equal(tool.argumentsSection.hidden, true);
  assert.equal(tool.argumentsBody.textContent, "");
  assert.equal(tool.resultSection.hidden, true);
  assert.equal(tool.resultBody.textContent, "");

  const emptyRedacted = renderer.toolOutput({
    agent: "Lead",
    name: "read",
    tool_call_id: "tool-empty-redacted",
    chars: 0,
    redacted: true,
  });
  assert.equal(
    emptyRedacted.outputBody.textContent,
    "0 chars received\nFull output available in EvoFlux Desktop",
  );
});

test("redacted Thinking history renders a disclosure before later text", () => {
  const { context } = loadRenderer();
  const target = new FakeElement("div");
  const renderer = context.WebBridgeTypedBlocks.create({
    createTurn() { return { item: new FakeElement("article"), content: new FakeElement("div") }; },
    renderMarkdown(body, markdown) { body.textContent = markdown; },
  });

  assert.equal(renderer.renderHistory(target, [
    { type: "thinking", agent: "Lead", chars: 987 },
    { type: "text", agent: "Lead", content: "Visible answer" },
  ]), true);

  assert.equal(target.children.length, 2);
  const activityGroup = target.children[0];
  assert.equal(activityGroup.tagName, "DETAILS");
  assert.equal(activityGroup.classList.contains("activity-timeline"), true);
  assert.equal(activityGroup.open, false);
  const thinkingDisclosure = activityGroup.children[1].children[0].children[0].children[0];
  assert.equal(thinkingDisclosure.tagName, "DETAILS");
  assert.equal(thinkingDisclosure.children[0].children[1].textContent, "Thought · 987 chars");
  assert.equal(
    thinkingDisclosure.children[1].textContent,
    "Reasoning remains in EvoFlux Desktop.",
  );
  assert.equal(target.children[1].textContent, "Visible answer");
});
