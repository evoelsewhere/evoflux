"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const sidePanelSource = fs.readFileSync(path.join(root, "extensions/webbridge/sidepanel.js"), "utf8");
const sidePanelHtml = fs.readFileSync(path.join(root, "extensions/webbridge/sidepanel.html"), "utf8");
const backendSource = fs.readFileSync(path.join(root, "app/api/routes/team/webbridge.py"), "utf8");

function composerHelpers() {
  const start = sidePanelSource.indexOf("const BUILTIN_COMPOSER_COMMANDS");
  const end = sidePanelSource.indexOf("\nasync function sendMessage", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({
    composerCatalog: {
      commands: [
        { id: "continue", label: "Continue", description: "Continue" },
        { id: "review", label: "Review", description: "Review code" },
      ],
      snippets: [{ id: "git/check", label: "git:check", description: "Git status" }],
      refs: [
        { path: "src", name: "src", type: "directory" },
        { path: "src/app.js", name: "app.js", type: "file" },
      ],
    },
  });
  vm.runInContext(`
    ${sidePanelSource.slice(start, end)}
    globalThis.activeComposerTrigger = activeComposerTrigger;
    globalThis.composerSuggestionRows = composerSuggestionRows;
    globalThis.workflowInputs = workflowInputs;
  `, context, { filename: "sidepanel-composer-parity.js" });
  return context;
}

test("composer detects and filters slash, snippet, and workspace reference triggers", () => {
  const context = composerHelpers();
  assert.equal(context.activeComposerTrigger("/cont").type, "command");
  assert.equal(context.activeComposerTrigger("/cont").query, "cont");
  assert.equal(context.activeComposerTrigger("Use #git/ch").type, "snippet");
  assert.equal(context.activeComposerTrigger("Read @src/ap").type, "reference");
  assert.equal(context.activeComposerTrigger("mail user@example.com"), null);

  const commandRows = context.composerSuggestionRows(context.activeComposerTrigger("/rev"));
  assert.equal(commandRows.length, 1);
  assert.equal(commandRows[0].id, "review");
  const referenceRows = context.composerSuggestionRows(context.activeComposerTrigger("Read @app"));
  assert.equal(referenceRows.length, 1);
  assert.equal(referenceRows[0].path, "src/app.js");
});

test("workflow composer parses name=value inputs and reports required values", () => {
  const context = composerHelpers();
  const entry = {
    inputs: [
      { name: "version", required: true },
      { name: "channel", required: false, default: "stable" },
    ],
  };
  const missing = context.workflowInputs(entry, "");
  assert.deepEqual(JSON.parse(JSON.stringify(missing)), {
    values: { channel: "stable" },
    missing: ["version"],
  });
  const complete = context.workflowInputs(entry, 'version="1.2.3" channel=beta');
  assert.deepEqual(JSON.parse(JSON.stringify(complete)), {
    values: { version: "1.2.3", channel: "beta" },
    missing: [],
  });
});

test("history projection keeps chronology while dropping protected raw payloads", () => {
  const start = sidePanelSource.indexOf("function protectedHistoryBlocks");
  const end = sidePanelSource.indexOf("\nfunction appendMessage", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  vm.runInContext(
    `${sidePanelSource.slice(start, end)}\nglobalThis.project = protectedHistoryBlocks;`,
    context,
    { filename: "sidepanel-protected-history.js" },
  );
  const blocks = context.project([
    { type: "text", content: "before" },
    { type: "thinking", content: "private reasoning" },
    {
      type: "tool",
      name: "shell",
      tool_call_id: "tool-1",
      arguments: { token: "must-not-leak" },
      output: "private output",
      result: "private result",
      done: true,
    },
    { type: "text", content: "after" },
  ]);

  assert.deepEqual(
    JSON.parse(JSON.stringify(blocks.map((block) => block.type))),
    ["text", "thinking", "tool", "text"],
  );
  assert.equal(blocks[1].chars, "private reasoning".length);
  const serialized = JSON.stringify(blocks);
  assert.doesNotMatch(serialized, /private reasoning|must-not-leak|private output|private result/);
});

test("model catalog accepts canonical and wrapped payloads and keeps the active session model", () => {
  const start = sidePanelSource.indexOf("function normalizeBrowserModels");
  const end = sidePanelSource.indexOf("\nasync function loadBrowserModels", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({ currentSessionModel: "codex:gpt-active" });
  vm.runInContext(
    `${sidePanelSource.slice(start, end)}\nglobalThis.normalize = normalizeBrowserModels;`,
    context,
    { filename: "sidepanel-model-catalog.js" },
  );

  const canonical = context.normalize([
    { id: "openai:gpt-test", provider: "openai", model: "gpt-test", thinking_levels: ["low", "low", "high"] },
  ]);
  assert.deepEqual(
    JSON.parse(JSON.stringify(canonical.map((entry) => entry.id))),
    ["codex:gpt-active", "openai:gpt-test"],
  );
  assert.deepEqual(JSON.parse(JSON.stringify(canonical[1].thinking_levels)), ["low", "high"]);

  const wrapped = context.normalize({ models: [{ id: "codex:gpt-active", thinking_levels: ["medium"] }] });
  assert.equal(wrapped.length, 1);
  assert.equal(wrapped[0].provider, "codex");
  assert.equal(wrapped[0].model, "gpt-active");
});

test("Side Chat exposes canonical turn, queue, gate, and composer controls", () => {
  for (const id of [
    "continueBtn", "undoTurnBtn", "redoTurnBtn", "revertNotice", "queuePanel",
    "composerMenu", "shellMode", "desktopGateActions", "desktopGatePayload",
  ]) assert.match(sidePanelHtml, new RegExp(`id="${id}"`));

  assert.match(sidePanelSource, /\/queued-messages/);
  assert.match(sidePanelSource, /\/composer-catalog/);
  assert.match(sidePanelSource, /\/composer\/workflows\/\$\{encodeURIComponent\(name\)\}\/run/);
  assert.match(sidePanelSource, /shell,/);
  assert.match(sidePanelSource, /type === "tool_output_delta"/);
  assert.match(sidePanelSource, /type === "widget_delta"/);
  assert.match(sidePanelSource, /type === "plan_approval_requested"/);
  assert.match(sidePanelHtml, /chat-renderer\.js/);
  assert.match(sidePanelHtml, /transcript-follow\.js/);
  assert.match(sidePanelHtml, /id="transcriptLatestBtn"/);
  assert.match(sidePanelSource, /WebBridgeTranscriptFollow\.create/);

  assert.match(backendSource, /\/sessions\/\{session_id\}\/commands/);
  assert.match(backendSource, /\/sessions\/\{session_id\}\/queued-messages/);
  assert.match(backendSource, /\/sessions\/\{session_id\}\/composer-catalog/);
  assert.match(backendSource, /\/sessions\/\{session_id\}\/composer\/workflows\/\{name\}\/run/);
  assert.match(backendSource, /"tool_output_delta"/);
  assert.match(backendSource, /"widget_delta"/);
});
