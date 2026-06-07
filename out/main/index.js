"use strict";
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));
const electron = require("electron");
const path = require("path");
const OpenAI = require("openai");
const Store = require("electron-store");
const child_process = require("child_process");
const util = require("util");
const nanoid = require("nanoid");
const promises = require("fs/promises");
const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS workflow (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  dsl_json TEXT NOT NULL,
  config_json TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  input_json TEXT,
  output_json TEXT,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  FOREIGN KEY (workflow_id) REFERENCES workflow(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS node_runs (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  node_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  input_json TEXT,
  output_json TEXT,
  error TEXT,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_semantic (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  type TEXT NOT NULL,
  content TEXT NOT NULL,
  embedding BLOB,
  metadata_json TEXT,
  created_at INTEGER NOT NULL,
  access_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memory_episodic (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  task_description TEXT,
  trajectory_json TEXT NOT NULL,
  outcome TEXT NOT NULL,
  feedback TEXT,
  embedding BLOB,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_procedural (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  pattern TEXT NOT NULL,
  source_episodes_json TEXT,
  usage_count INTEGER DEFAULT 0,
  success_rate REAL DEFAULT 0,
  maturity_score REAL DEFAULT 0,
  embedding BLOB,
  created_at INTEGER NOT NULL,
  last_used_at INTEGER
);

CREATE TABLE IF NOT EXISTS memory_edges (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  type TEXT NOT NULL,
  weight REAL DEFAULT 1.0,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS env_variables (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  is_secret INTEGER DEFAULT 0,
  UNIQUE(workflow_id, key)
);

CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_node_runs_run ON node_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_semantic_workflow ON memory_semantic(workflow_id);
CREATE INDEX IF NOT EXISTS idx_episodic_workflow ON memory_episodic(workflow_id);
CREATE INDEX IF NOT EXISTS idx_procedural_workflow ON memory_procedural(workflow_id);
CREATE INDEX IF NOT EXISTS idx_edges_source ON memory_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON memory_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_env_workflow ON env_variables(workflow_id);
`;
let dbInstance = null;
function openDatabase(dbPath) {
  if (dbInstance) return dbInstance;
  try {
    const Database = require("better-sqlite3");
    const db = new Database(dbPath);
    db.pragma("journal_mode = WAL");
    db.pragma("foreign_keys = ON");
    db.exec(SCHEMA_SQL);
    dbInstance = db;
    return db;
  } catch {
    dbInstance = createInMemoryAdapter();
    dbInstance.exec(SCHEMA_SQL);
    return dbInstance;
  }
}
function getDatabase() {
  if (!dbInstance) throw new Error("Database not initialized. Call openDatabase() first.");
  return dbInstance;
}
function matchWhere(whereClause, row, params) {
  if (!whereClause) return true;
  let idx = 0;
  const resolved = whereClause.replace(/\?/g, () => {
    const v = params[idx++];
    return typeof v === "string" ? `'${v}'` : String(v ?? "null");
  });
  const conditions = resolved.split(/\s+AND\s+/i);
  for (const cond of conditions) {
    const m = cond.match(/(\w+)\s*=\s*'?(.+?)'?\s*$/);
    if (m) {
      const [, col, val] = m;
      if (String(row[col]) !== val) return false;
    }
  }
  return true;
}
function createInMemoryAdapter() {
  const tables = /* @__PURE__ */ new Map();
  return {
    exec(sql) {
      const statements = sql.split(";").filter((s) => s.trim());
      for (const stmt of statements) {
        const m = stmt.match(/CREATE TABLE IF NOT EXISTS (\w+)/i);
        if (m && !tables.has(m[1])) tables.set(m[1], /* @__PURE__ */ new Map());
      }
    },
    prepare(sql) {
      return {
        run(...params) {
          const insertMatch = sql.match(/INSERT OR REPLACE INTO (\w+)\s*\(([^)]+)\)\s*VALUES/i);
          if (insertMatch) {
            const [, table, colsStr] = insertMatch;
            const t = tables.get(table);
            if (!t) return { changes: 0 };
            const cols = colsStr.split(",").map((c) => c.trim());
            const row = {};
            cols.forEach((col, i) => {
              row[col] = params[i];
            });
            t.set(String(row.id), row);
            return { changes: 1 };
          }
          const insertMatch2 = sql.match(/INSERT INTO (\w+)\s*\(([^)]+)\)\s*VALUES/i);
          if (insertMatch2) {
            const [, table, colsStr] = insertMatch2;
            const t = tables.get(table);
            if (!t) return { changes: 0 };
            const cols = colsStr.split(",").map((c) => c.trim());
            const row = {};
            cols.forEach((col, i) => {
              row[col] = params[i];
            });
            t.set(String(row.id), row);
            return { changes: 1 };
          }
          const updateMatch = sql.match(/UPDATE (\w+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?$/i);
          if (updateMatch) {
            const [, table, setClause, whereClause] = updateMatch;
            const t = tables.get(table);
            if (!t) return { changes: 0 };
            let setIdx = 0;
            const setParts = setClause.split(",").map((s) => s.trim());
            const assignments = [];
            for (const part of setParts) {
              const m = part.match(/(\w+)\s*=\s*\?/);
              if (m) assignments.push([m[1], params[setIdx++]]);
            }
            const whereParams = params.slice(setIdx);
            let changes = 0;
            for (const [id, row] of t) {
              if (whereClause ? matchWhere(whereClause, row, whereParams) : true) {
                for (const [col, val] of assignments) row[col] = val;
                t.set(id, row);
                changes++;
              }
            }
            return { changes };
          }
          const deleteMatch = sql.match(/DELETE FROM (\w+)(?:\s+WHERE\s+(.+))?$/i);
          if (deleteMatch) {
            const [, table, whereClause] = deleteMatch;
            const t = tables.get(table);
            if (!t) return { changes: 0 };
            const before = t.size;
            if (whereClause) {
              for (const [id, row] of t) {
                if (matchWhere(whereClause, row, params)) t.delete(id);
              }
            } else {
              t.clear();
            }
            return { changes: before - t.size };
          }
          return { changes: 0 };
        },
        get(...params) {
          const selectMatch = sql.match(/SELECT (.+?) FROM (\w+)(?:\s+WHERE\s+(.+))?$/i);
          if (!selectMatch) return void 0;
          const [, _cols, table, whereClause] = selectMatch;
          const t = tables.get(table);
          if (!t) return void 0;
          for (const [, row] of t) {
            if (matchWhere(whereClause || "", row, params)) return { ...row };
          }
          return void 0;
        },
        all(...params) {
          const selectMatch = sql.match(/SELECT (.+?) FROM (\w+)(?:\s+WHERE\s+(.+?))?(?:\s+ORDER BY\s+(.+?))?(?:\s+LIMIT\s+(\d+))?$/i);
          if (!selectMatch) return [];
          const [, _cols, table, whereClause] = selectMatch;
          const t = tables.get(table);
          if (!t) return [];
          const results = [];
          for (const [, row] of t) {
            if (matchWhere(whereClause || "", row, params)) results.push({ ...row });
          }
          return results;
        }
      };
    },
    close() {
    },
    pragma() {
      return void 0;
    }
  };
}
const execFileAsync = util.promisify(child_process.execFile);
const store$1 = new Store();
function resolveConfig(provider, override) {
  const base = getProviderConfig(provider);
  return {
    ...base,
    apiKey: override?.apiKey || base.apiKey,
    baseUrl: override?.baseUrl || base.baseUrl
  };
}
function getProviderConfig(provider) {
  switch (provider) {
    case "openai":
      return {
        type: "openai",
        apiKey: store$1.get("settings.openaiApiKey"),
        defaultModel: "gpt-4o-mini"
      };
    case "ollama":
      return {
        type: "ollama",
        baseUrl: store$1.get("settings.ollamaUrl") || "http://localhost:11434",
        defaultModel: "llama3.2"
      };
    case "anthropic":
      return {
        type: "anthropic",
        apiKey: store$1.get("settings.anthropicApiKey"),
        baseUrl: store$1.get("settings.anthropicBaseUrl") || "https://api.anthropic.com",
        defaultModel: "claude-sonnet-4-20250514"
      };
    case "claude-cli":
      return { type: "claude-cli", defaultModel: "claude" };
    case "copilot-cli":
      return { type: "copilot-cli", defaultModel: "copilot" };
    case "openai-compatible":
      return { type: "openai-compatible", apiKey: "", baseUrl: "", defaultModel: "" };
  }
}
let openaiClient = null;
function getOpenAIClient() {
  if (!openaiClient) {
    const config = getProviderConfig("openai");
    if (!config.apiKey) throw new Error("OpenAI API key not configured");
    openaiClient = new OpenAI({ apiKey: config.apiKey });
  }
  return openaiClient;
}
async function chatWithOpenAI(messages, model) {
  const client = getOpenAIClient();
  const response = await client.chat.completions.create({
    model: model || "gpt-4o-mini",
    messages
  });
  return response.choices[0]?.message?.content || "";
}
async function chatWithAnthropic(messages, model, cfg) {
  const config = cfg || getProviderConfig("anthropic");
  if (!config.apiKey) throw new Error("Anthropic API key not configured");
  const systemMsg = messages.find((m) => m.role === "system");
  const nonSystemMsgs = messages.filter((m) => m.role !== "system");
  const response = await fetch(`${config.baseUrl}/v1/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": config.apiKey,
      "anthropic-version": "2023-06-01"
    },
    body: JSON.stringify({
      model: model || config.defaultModel,
      max_tokens: 4096,
      system: systemMsg?.content || void 0,
      messages: nonSystemMsgs.map((m) => ({ role: m.role === "user" ? "user" : "assistant", content: m.content }))
    })
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Anthropic error (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return data.content?.[0]?.text || "";
}
async function chatWithOllama(messages, model, cfg) {
  const config = cfg || getProviderConfig("ollama");
  const response = await fetch(`${config.baseUrl}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: model || config.defaultModel, messages, stream: false })
  });
  if (!response.ok) throw new Error(`Ollama error: ${response.statusText}`);
  const data = await response.json();
  return data.message?.content || "";
}
async function listOllamaModels() {
  const config = getProviderConfig("ollama");
  try {
    const response = await fetch(`${config.baseUrl}/api/tags`);
    if (!response.ok) return [];
    const data = await response.json();
    return data.models?.map((m) => m.name) || [];
  } catch {
    return [];
  }
}
async function chatWithClaudeCLI(messages, _model) {
  const prompt = messages.map((m) => {
    if (m.role === "system") return `System: ${m.content}`;
    if (m.role === "user") return `Human: ${m.content}`;
    return `Assistant: ${m.content}`;
  }).join("\n\n");
  try {
    const { stdout } = await execFileAsync("claude", ["--print", prompt], {
      timeout: 12e4,
      maxBuffer: 10 * 1024 * 1024
    });
    return stdout.trim();
  } catch (error) {
    const msg = error instanceof Error ? error.message : "Claude CLI failed";
    throw new Error(`Claude CLI error: ${msg}`);
  }
}
async function chatWithCopilotCLI(messages, _model) {
  const prompt = messages.filter((m) => m.role !== "system").map((m) => m.content).join("\n");
  try {
    const { stdout } = await execFileAsync("gh", ["copilot", "suggest", "-t", "shell", prompt], {
      timeout: 6e4,
      maxBuffer: 10 * 1024 * 1024
    });
    return stdout.trim();
  } catch (error) {
    const msg = error instanceof Error ? error.message : "Copilot CLI failed";
    throw new Error(`Copilot CLI error: ${msg}`);
  }
}
async function chat(provider, messages, model) {
  switch (provider) {
    case "openai":
      return chatWithOpenAI(messages, model);
    case "anthropic":
      return chatWithAnthropic(messages, model);
    case "ollama":
      return chatWithOllama(messages, model);
    case "claude-cli":
      return chatWithClaudeCLI(messages);
    case "copilot-cli":
      return chatWithCopilotCLI(messages);
    default:
      throw new Error(`Unknown provider: ${provider}`);
  }
}
async function listModels(provider) {
  switch (provider) {
    case "openai":
      return ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1-preview", "o1-mini"];
    case "anthropic":
      return ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"];
    case "ollama":
      return await listOllamaModels();
    case "claude-cli":
      return ["claude"];
    case "copilot-cli":
      return ["copilot"];
    default:
      return [];
  }
}
function saveModelConfig(provider, model, config) {
  try {
    const db = getDatabase();
    db.exec(`CREATE TABLE IF NOT EXISTS model_config (
      id TEXT PRIMARY KEY,
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      config_json TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )`);
    const now = Date.now();
    db.prepare("INSERT OR REPLACE INTO model_config (id, provider, model, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)").run(`${provider}:${model}`, provider, model, JSON.stringify(config), now, now);
  } catch {
  }
}
function getModelConfig(provider, model) {
  try {
    const db = getDatabase();
    const row = db.prepare("SELECT config_json FROM model_config WHERE id = ?").get(`${provider}:${model}`);
    return row ? JSON.parse(row.config_json) : null;
  } catch {
    return null;
  }
}
function listModelConfigs() {
  try {
    const db = getDatabase();
    const rows = db.prepare("SELECT provider, model, config_json FROM model_config ORDER BY updated_at DESC").all();
    return rows.map((r) => ({ provider: r.provider, model: r.model, config: JSON.parse(r.config_json) }));
  } catch {
    return [];
  }
}
function registerAIHandlers() {
  electron.ipcMain.handle("settings:save", async (_event, settings) => {
    if (settings && typeof settings === "object") {
      for (const [key, value] of Object.entries(settings)) {
        store$1.set(`settings.${key}`, value);
      }
    }
    return { success: true };
  });
  electron.ipcMain.handle("settings:load", async () => {
    return {
      providers: store$1.get("settings.providers") || [],
      appearance: store$1.get("settings.appearance") || null
    };
  });
  electron.ipcMain.handle("ai:chat", async (_event, messages, options) => {
    const provider = options?.provider || store$1.get("settings.aiProvider") || "openai";
    const model = options?.model || "";
    const config = resolveConfig(provider, options?.providerConfig);
    try {
      switch (provider) {
        case "openai":
        case "openai-compatible": {
          if (!config.apiKey) throw new Error(`${provider} API key not configured`);
          const client = new OpenAI({ apiKey: config.apiKey, baseURL: config.baseUrl });
          const response = await client.chat.completions.create({
            model: model || config.defaultModel,
            messages
          });
          return response.choices[0]?.message?.content || "";
        }
        case "anthropic":
          return await chatWithAnthropic(messages, model, config);
        case "ollama":
          return await chatWithOllama(messages, model, config);
        case "claude-cli":
          return await chatWithClaudeCLI(messages, model);
        case "copilot-cli":
          return await chatWithCopilotCLI(messages, model);
        default:
          throw new Error(`Unknown provider: ${provider}`);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Unknown error";
      throw new Error(`AI chat failed: ${msg}`);
    }
  });
  electron.ipcMain.handle("ai:stream-chat", async (event, messages, options) => {
    const provider = options?.provider || store$1.get("settings.aiProvider") || "openai";
    const model = options?.model || "";
    try {
      if (provider === "ollama") {
        const config = getProviderConfig("ollama");
        const response = await fetch(`${config.baseUrl}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: model || config.defaultModel, messages, stream: true })
        });
        if (!response.ok) throw new Error(`Ollama error: ${response.statusText}`);
        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        while (reader) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value);
          for (const line of chunk.split("\n").filter(Boolean)) {
            try {
              const data = JSON.parse(line);
              if (data.message?.content) event.sender.send("ai:stream-chunk", data.message.content);
            } catch {
            }
          }
        }
        return "Stream complete";
      }
      if (provider === "openai") {
        const client = getOpenAIClient();
        const stream = await client.chat.completions.create({
          model: model || "gpt-4o-mini",
          messages,
          stream: true
        });
        for await (const chunk of stream) {
          const content = chunk.choices[0]?.delta?.content;
          if (content) event.sender.send("ai:stream-chunk", content);
        }
        return "Stream complete";
      }
      const result = await chat(provider, messages, model);
      event.sender.send("ai:stream-chunk", result);
      return "Stream complete";
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Unknown error";
      throw new Error(`AI stream failed: ${msg}`);
    }
  });
  electron.ipcMain.handle("ai:list-models", async (_event, provider) => {
    const p = provider || store$1.get("settings.aiProvider") || "openai";
    return await listModels(p);
  });
  electron.ipcMain.handle("ai:test-connection", async (_event, provider, providerConfig) => {
    const cfg = resolveConfig(provider, providerConfig);
    try {
      switch (provider) {
        case "openai":
        case "openai-compatible": {
          if (!cfg.apiKey) return false;
          const client = new OpenAI({ apiKey: cfg.apiKey, baseURL: cfg.baseUrl });
          await client.models.list();
          return true;
        }
        case "anthropic": {
          if (!cfg.apiKey) return false;
          const res = await fetch(`${cfg.baseUrl}/v1/messages`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "x-api-key": cfg.apiKey, "anthropic-version": "2023-06-01" },
            body: JSON.stringify({ model: cfg.defaultModel, max_tokens: 1, messages: [{ role: "user", content: "hi" }] })
          });
          return res.ok || res.status === 400;
        }
        case "ollama": {
          const res = await fetch(`${cfg.baseUrl}/api/tags`);
          return res.ok;
        }
        case "claude-cli": {
          const { stdout } = await execFileAsync("claude", ["--version"], { timeout: 5e3 });
          return stdout.length > 0;
        }
        case "copilot-cli": {
          const { stdout } = await execFileAsync("gh", ["copilot", "--version"], { timeout: 5e3 });
          return stdout.length > 0;
        }
        default:
          return false;
      }
    } catch {
      return false;
    }
  });
  electron.ipcMain.handle("ai:save-model-config", async (_event, provider, model, config) => {
    saveModelConfig(provider, model, config);
    return { success: true };
  });
  electron.ipcMain.handle("ai:get-model-config", async (_event, provider, model) => {
    return getModelConfig(provider, model);
  });
  electron.ipcMain.handle("ai:list-model-configs", async () => {
    return listModelConfigs();
  });
}
const store = new Store({
  defaults: { workflows: {} }
});
function registerWorkflowHandlers() {
  electron.ipcMain.handle("workflow:save", async (_event, workflow) => {
    const workflows = store.get("workflows") || {};
    const id = workflow.id || nanoid.nanoid();
    const now = (/* @__PURE__ */ new Date()).toISOString();
    const savedWorkflow = {
      id,
      name: workflow.name || "Untitled Workflow",
      description: workflow.description ?? workflows[id]?.description ?? "",
      nodes: workflow.nodes || [],
      edges: workflow.edges || [],
      createdAt: workflows[id]?.createdAt || now,
      updatedAt: now
    };
    workflows[id] = savedWorkflow;
    store.set("workflows", workflows);
    return savedWorkflow;
  });
  electron.ipcMain.handle("workflow:load", async (_event, id) => {
    const workflows = store.get("workflows") || {};
    return workflows[id] || null;
  });
  electron.ipcMain.handle("workflow:list", async () => {
    const workflows = store.get("workflows") || {};
    return Object.values(workflows).sort(
      (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
    );
  });
  electron.ipcMain.handle("workflow:delete", async (_event, id) => {
    const workflows = store.get("workflows") || {};
    delete workflows[id];
    store.set("workflows", workflows);
    return true;
  });
}
class Segment {
  constructor(value) {
    this.type = Segment.resolveType(value);
    this.value = value;
  }
  get text() {
    if (this.value === null || this.value === void 0) return "";
    if (typeof this.value === "object") return JSON.stringify(this.value);
    return String(this.value);
  }
  get number() {
    const n = Number(this.value);
    if (isNaN(n)) return 0;
    return n;
  }
  get bool() {
    if (typeof this.value === "boolean") return this.value;
    if (typeof this.value === "string") return this.value === "true";
    if (typeof this.value === "number") return this.value !== 0;
    return false;
  }
  static resolveType(value) {
    if (value === null || value === void 0) return "null";
    if (Array.isArray(value)) return "array";
    return typeof value;
  }
}
class VariablePool {
  constructor() {
    this.segments = /* @__PURE__ */ new Map();
  }
  set(selector, value) {
    const [nodeId, key] = selector;
    if (!this.segments.has(nodeId)) {
      this.segments.set(nodeId, /* @__PURE__ */ new Map());
    }
    this.segments.get(nodeId).set(key, new Segment(value));
  }
  get(selector) {
    const [nodeId, key] = selector;
    return this.segments.get(nodeId)?.get(key)?.value;
  }
  getSegment(selector) {
    const [nodeId, key] = selector;
    return this.segments.get(nodeId)?.get(key);
  }
  getByPrefix(prefix) {
    return this.segments.get(prefix) || /* @__PURE__ */ new Map();
  }
  has(selector) {
    const [nodeId, key] = selector;
    return this.segments.get(nodeId)?.has(key) ?? false;
  }
  delete(selector) {
    const [nodeId, key] = selector;
    this.segments.get(nodeId)?.delete(key);
  }
  deleteNode(nodeId) {
    this.segments.delete(nodeId);
  }
  clear() {
    this.segments.clear();
  }
  resolve(template) {
    return template.replace(/\{\{#([^#]+)#\}\}/g, (_, ref) => {
      const parts = ref.split(".");
      if (parts.length !== 2) return "";
      const value = this.get([parts[0], parts[1]]);
      if (value === void 0 || value === null) return "";
      if (typeof value === "object") return JSON.stringify(value);
      return String(value);
    });
  }
  toJSON() {
    const result = {};
    for (const [nodeId, keys] of this.segments) {
      result[nodeId] = {};
      for (const [key, segment] of keys) {
        result[nodeId][key] = segment.value;
      }
    }
    return result;
  }
}
class BaseNode {
  validateInputs(inputs, metadata) {
    for (const port of metadata.inputs) {
      if (port.required && (inputs[port.name] === void 0 || inputs[port.name] === null)) {
        throw new Error(`Required input '${port.name}' (${port.label}) is missing`);
      }
    }
  }
}
const nodeRegistry = /* @__PURE__ */ new Map();
class NodeFactory {
  static create(type) {
    const NodeClass = nodeRegistry.get(type);
    if (!NodeClass) {
      throw new Error(`Unknown node type: '${type}'. Registered types: ${Array.from(nodeRegistry.keys()).join(", ")}`);
    }
    return new NodeClass();
  }
  static has(type) {
    return nodeRegistry.has(type);
  }
  static getRegisteredTypes() {
    return Array.from(nodeRegistry.keys());
  }
  static getMetadata(type) {
    return NodeFactory.create(type).getMetadata();
  }
  static getAllMetadata() {
    return Array.from(nodeRegistry.keys()).map((type) => NodeFactory.getMetadata(type));
  }
}
class WorkflowError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "WorkflowError";
  }
}
class NodeExecutionError extends WorkflowError {
  constructor(nodeId, nodeType, message, options) {
    super(`[${nodeType}:${nodeId}] ${message}`, options);
    this.name = "NodeExecutionError";
    this.nodeId = nodeId;
    this.nodeType = nodeType;
  }
}
class GraphError extends WorkflowError {
  constructor(message, options) {
    super(message, options);
    this.name = "GraphError";
  }
}
class CycleDetectedError extends GraphError {
  constructor(cycle) {
    super(`Cycle detected: ${cycle.join(" → ")}`);
    this.name = "CycleDetectedError";
    this.cycle = cycle;
  }
}
class TemplateError extends WorkflowError {
  constructor(message, options) {
    super(message, options);
    this.name = "TemplateError";
  }
}
class ExecutionLimitError extends WorkflowError {
  constructor(message, options) {
    super(message, options);
    this.name = "ExecutionLimitError";
  }
}
class AgentError extends WorkflowError {
  constructor(message, options) {
    super(message, options);
    this.name = "AgentError";
  }
}
const REF_PATTERN = /\{\{#([^#]+)#\}\}/g;
function resolveTemplate(template, pool) {
  return template.replace(REF_PATTERN, (_, ref) => {
    const parts = ref.split(".");
    if (parts.length !== 2) {
      throw new TemplateError(`Invalid variable reference: '{{#${ref}#}}'. Expected format: nodeId.key`);
    }
    const [nodeId, key] = parts;
    const value = pool.get([nodeId, key]);
    if (value === void 0 || value === null) return "";
    if (typeof value === "object") return JSON.stringify(value, null, 2);
    return String(value);
  });
}
function resolveValue(value, pool) {
  if (typeof value === "string") {
    return resolveTemplate(value, pool);
  }
  if (Array.isArray(value)) {
    return value.map((item) => resolveValue(item, pool));
  }
  if (value !== null && typeof value === "object") {
    const result = {};
    for (const [k, v] of Object.entries(value)) {
      result[k] = resolveValue(v, pool);
    }
    return result;
  }
  return value;
}
class LayerManager {
  constructor() {
    this.layers = [];
  }
  add(layer) {
    this.layers.push(layer);
  }
  remove(name) {
    this.layers = this.layers.filter((l) => l.name !== name);
  }
  async emitGraphStart() {
    for (const layer of this.layers) {
      await layer.onGraphStart?.();
    }
  }
  async emitGraphEnd(result) {
    for (const layer of this.layers) {
      await layer.onGraphEnd?.(result);
    }
  }
  async emitNodeStart(node) {
    for (const layer of this.layers) {
      await layer.onNodeStart?.(node);
    }
  }
  async emitNodeEnd(node, output) {
    for (const layer of this.layers) {
      await layer.onNodeEnd?.(node, output);
    }
  }
  async emitNodeError(node, error) {
    for (const layer of this.layers) {
      await layer.onNodeError?.(node, error);
    }
  }
}
class UILayer {
  constructor(emit) {
    this.name = "ui";
    this.emit = emit;
  }
  onGraphStart() {
    this.emit({ type: "graph:start", timestamp: Date.now() });
  }
  onGraphEnd(result) {
    this.emit({ type: "graph:end", timestamp: Date.now(), ...result });
  }
  onNodeStart(node) {
    this.emit({ type: "node:start", nodeId: node.id, timestamp: Date.now() });
  }
  onNodeEnd(node, output) {
    this.emit({ type: "node:complete", nodeId: node.id, output, timestamp: Date.now() });
  }
  onNodeError(node, error) {
    this.emit({ type: "node:error", nodeId: node.id, error, timestamp: Date.now() });
  }
}
class GraphEngine {
  constructor(config) {
    this.graph = config.graph;
    this.variablePool = config.variablePool || new VariablePool();
    this.layers = new LayerManager();
    this.maxSteps = config.maxSteps || 1e3;
    this.maxTimeMs = config.maxTimeMs || 6e5;
    this.maxParallel = config.maxParallel || 5;
    for (const layer of config.layers || []) {
      this.layers.add(layer);
    }
  }
  async *runSequential(options = {}) {
    const startTime = Date.now();
    let steps = 0;
    let completed = 0;
    let failed = 0;
    const sorted = this.graph.topologicalSort();
    yield { type: "graph:start", timestamp: Date.now() };
    await this.layers.emitGraphStart();
    for (const nodeId of sorted) {
      if (options.signal?.aborted) {
        yield { type: "graph:aborted", timestamp: Date.now() };
        return;
      }
      if (Date.now() - startTime > this.maxTimeMs) {
        throw new ExecutionLimitError(`Execution timeout: exceeded ${this.maxTimeMs}ms`);
      }
      if (++steps > this.maxSteps) {
        throw new ExecutionLimitError(`Execution limit: exceeded ${this.maxSteps} steps`);
      }
      const node = this.graph.getNode(nodeId);
      const startEvent = { type: "node:start", nodeId, timestamp: Date.now() };
      yield startEvent;
      await this.layers.emitNodeStart(node);
      try {
        const output = await this.executeNode(node, this.variablePool, options.signal);
        this.variablePool.set([nodeId, "__output__"], output);
        completed++;
        const completeEvent = { type: "node:complete", nodeId, output, timestamp: Date.now() };
        yield completeEvent;
        await this.layers.emitNodeEnd(node, output);
      } catch (error) {
        failed++;
        const err = error instanceof Error ? error : new Error(String(error));
        const errorEvent = { type: "node:error", nodeId, error: err, timestamp: Date.now() };
        yield errorEvent;
        await this.layers.emitNodeError(node, err);
        throw error;
      }
    }
    const endEvent = { type: "graph:complete", timestamp: Date.now() };
    yield endEvent;
    await this.layers.emitGraphEnd({ completed, failed });
  }
  async *runParallel(options = {}) {
    const startTime = Date.now();
    let steps = 0;
    let completed = 0;
    let failed = 0;
    const groups = this.graph.getParallelGroups();
    yield { type: "graph:start", timestamp: Date.now() };
    await this.layers.emitGraphStart();
    for (const group of groups) {
      if (options.signal?.aborted) {
        yield { type: "graph:aborted", timestamp: Date.now() };
        return;
      }
      if (Date.now() - startTime > this.maxTimeMs) {
        throw new ExecutionLimitError(`Execution timeout: exceeded ${this.maxTimeMs}ms`);
      }
      if (group.length === 1) {
        steps++;
        if (steps > this.maxSteps) {
          throw new ExecutionLimitError(`Execution limit: exceeded ${this.maxSteps} steps`);
        }
        const nodeId = group[0];
        const node = this.graph.getNode(nodeId);
        yield { type: "node:start", nodeId, timestamp: Date.now() };
        await this.layers.emitNodeStart(node);
        try {
          const output = await this.executeNode(node, this.variablePool, options.signal);
          this.variablePool.set([nodeId, "__output__"], output);
          completed++;
          yield { type: "node:complete", nodeId, output, timestamp: Date.now() };
          await this.layers.emitNodeEnd(node, output);
        } catch (error) {
          failed++;
          const err = error instanceof Error ? error : new Error(String(error));
          yield { type: "node:error", nodeId, error: err, timestamp: Date.now() };
          await this.layers.emitNodeError(node, err);
          throw error;
        }
      } else {
        const batch = group.slice(0, this.maxParallel);
        for (const nodeId of batch) {
          steps++;
          if (steps > this.maxSteps) {
            throw new ExecutionLimitError(`Execution limit: exceeded ${this.maxSteps} steps`);
          }
          yield { type: "node:start", nodeId, timestamp: Date.now() };
        }
        const results = await Promise.allSettled(
          batch.map(async (nodeId) => {
            const node = this.graph.getNode(nodeId);
            await this.layers.emitNodeStart(node);
            const output = await this.executeNode(node, this.variablePool, options.signal);
            this.variablePool.set([nodeId, "__output__"], output);
            return { nodeId, output };
          })
        );
        for (const result of results) {
          if (result.status === "fulfilled") {
            completed++;
            const { nodeId, output } = result.value;
            yield { type: "node:complete", nodeId, output, timestamp: Date.now() };
            await this.layers.emitNodeEnd(this.graph.getNode(nodeId), output);
          } else {
            failed++;
            const reason = result.reason instanceof Error ? result.reason : new Error(String(result.reason));
            yield { type: "node:error", error: reason, timestamp: Date.now() };
            throw reason;
          }
        }
      }
    }
    yield { type: "graph:complete", timestamp: Date.now() };
    await this.layers.emitGraphEnd({ completed, failed });
  }
  async executeNode(node, pool, signal) {
    const nodeInstance = NodeFactory.create(node.type);
    const metadata = nodeInstance.getMetadata();
    const inputs = {};
    for (const port of metadata.inputs) {
      const value = pool.get([node.id, port.name]);
      if (value !== void 0) {
        inputs[port.name] = resolveValue(value, pool);
      }
    }
    const config = resolveValue(node.data, pool);
    nodeInstance.validateInputs(inputs, metadata);
    try {
      return await nodeInstance.run(inputs, config, pool, {
        nodeId: node.id,
        signal
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      throw new NodeExecutionError(node.id, node.type, message, { cause: error });
    }
  }
}
class Graph {
  constructor() {
    this.nodes = /* @__PURE__ */ new Map();
    this.outgoing = /* @__PURE__ */ new Map();
    this.incoming = /* @__PURE__ */ new Map();
    this.edgesList = [];
  }
  addNode(node) {
    if (this.nodes.has(node.id)) {
      throw new GraphError(`Node '${node.id}' already exists`);
    }
    this.nodes.set(node.id, node);
    if (!this.outgoing.has(node.id)) this.outgoing.set(node.id, /* @__PURE__ */ new Set());
    if (!this.incoming.has(node.id)) this.incoming.set(node.id, /* @__PURE__ */ new Set());
  }
  removeNode(nodeId) {
    if (!this.nodes.has(nodeId)) return;
    const outgoing = this.outgoing.get(nodeId) || /* @__PURE__ */ new Set();
    const incoming = this.incoming.get(nodeId) || /* @__PURE__ */ new Set();
    for (const target of outgoing) {
      this.incoming.get(target)?.delete(nodeId);
    }
    for (const source of incoming) {
      this.outgoing.get(source)?.delete(nodeId);
    }
    this.edgesList = this.edgesList.filter((e) => e.source !== nodeId && e.target !== nodeId);
    this.nodes.delete(nodeId);
    this.outgoing.delete(nodeId);
    this.incoming.delete(nodeId);
  }
  addEdge(edge) {
    if (!this.nodes.has(edge.source)) {
      throw new GraphError(`Source node '${edge.source}' not found`);
    }
    if (!this.nodes.has(edge.target)) {
      throw new GraphError(`Target node '${edge.target}' not found`);
    }
    this.outgoing.get(edge.source).add(edge.target);
    this.incoming.get(edge.target).add(edge.source);
    this.edgesList.push(edge);
  }
  removeEdge(edgeId) {
    const edge = this.edgesList.find((e) => e.id === edgeId);
    if (!edge) return;
    this.outgoing.get(edge.source)?.delete(edge.target);
    this.incoming.get(edge.target)?.delete(edge.source);
    this.edgesList = this.edgesList.filter((e) => e.id !== edgeId);
  }
  getNode(nodeId) {
    return this.nodes.get(nodeId);
  }
  getNodes() {
    return Array.from(this.nodes.values());
  }
  getEdges() {
    return [...this.edgesList];
  }
  getOutgoing(nodeId) {
    return Array.from(this.outgoing.get(nodeId) || []);
  }
  getIncoming(nodeId) {
    return Array.from(this.incoming.get(nodeId) || []);
  }
  getRoots() {
    const roots = [];
    for (const [nodeId, deps] of this.incoming) {
      if (deps.size === 0) roots.push(nodeId);
    }
    return roots;
  }
  getLeaves() {
    const leaves = [];
    for (const [nodeId, deps] of this.outgoing) {
      if (deps.size === 0) leaves.push(nodeId);
    }
    return leaves;
  }
  get size() {
    return this.nodes.size;
  }
  hasNode(nodeId) {
    return this.nodes.has(nodeId);
  }
  topologicalSort() {
    const inDegree = /* @__PURE__ */ new Map();
    const adjacency = /* @__PURE__ */ new Map();
    for (const nodeId of this.nodes.keys()) {
      inDegree.set(nodeId, 0);
      adjacency.set(nodeId, []);
    }
    for (const edge of this.edgesList) {
      adjacency.get(edge.source).push(edge.target);
      inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1);
    }
    const queue = [];
    for (const [nodeId, degree] of inDegree) {
      if (degree === 0) queue.push(nodeId);
    }
    const sorted = [];
    while (queue.length > 0) {
      const current = queue.shift();
      sorted.push(current);
      for (const neighbor of adjacency.get(current) || []) {
        const newDegree = (inDegree.get(neighbor) || 1) - 1;
        inDegree.set(neighbor, newDegree);
        if (newDegree === 0) queue.push(neighbor);
      }
    }
    if (sorted.length !== this.nodes.size) {
      const visited = new Set(sorted);
      const cycleNodes = [];
      for (const nodeId of this.nodes.keys()) {
        if (!visited.has(nodeId)) cycleNodes.push(nodeId);
      }
      throw new CycleDetectedError(cycleNodes);
    }
    return sorted;
  }
  getParallelGroups() {
    const sorted = this.topologicalSort();
    const levels = /* @__PURE__ */ new Map();
    for (const nodeId of sorted) {
      const deps = this.incoming.get(nodeId) || /* @__PURE__ */ new Set();
      if (deps.size === 0) {
        levels.set(nodeId, 0);
      } else {
        let maxLevel = 0;
        for (const dep of deps) {
          maxLevel = Math.max(maxLevel, levels.get(dep) || 0);
        }
        levels.set(nodeId, maxLevel + 1);
      }
    }
    const groups = /* @__PURE__ */ new Map();
    for (const [nodeId, level] of levels) {
      if (!groups.has(level)) groups.set(level, []);
      groups.get(level).push(nodeId);
    }
    const result = [];
    const sortedLevels = Array.from(groups.keys()).sort((a, b) => a - b);
    for (const level of sortedLevels) {
      result.push(groups.get(level));
    }
    return result;
  }
  toJSON() {
    return {
      nodes: this.getNodes(),
      edges: this.getEdges()
    };
  }
}
function deserializeGraph(dsl) {
  const graph = new Graph();
  for (const node of dsl.graph.nodes) {
    graph.addNode({
      id: node.id,
      type: node.type,
      data: node.data,
      position: node.position
    });
  }
  for (const edge of dsl.graph.edges) {
    graph.addEdge({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
      label: edge.label
    });
  }
  return graph;
}
class StartNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "start";
  }
  getMetadata() {
    return {
      type: "start",
      label: "Start",
      icon: "play-circle",
      category: "trigger",
      description: "Workflow entry point. Defines input variables.",
      inputs: [],
      outputs: [],
      defaultConfig: { variables: [] }
    };
  }
  async run(_inputs, config, pool, context) {
    const cfg = config;
    const result = {};
    for (const v of cfg.variables || []) {
      const value = pool.get([context.nodeId, v.name]) ?? v.default ?? "";
      pool.set([context.nodeId, v.name], value);
      result[v.name] = value;
    }
    return result;
  }
}
class EndNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "end";
  }
  getMetadata() {
    return {
      type: "end",
      label: "End",
      icon: "stop-circle",
      category: "trigger",
      description: "Workflow terminal node. Collects final outputs.",
      inputs: [{ name: "output", label: "Output", type: "string", required: false }],
      outputs: [],
      defaultConfig: {}
    };
  }
  async run(inputs, _config, _pool, _context) {
    return { final_output: inputs.output ?? "" };
  }
}
class LLMNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "llm";
  }
  getMetadata() {
    return {
      type: "llm",
      label: "LLM",
      icon: "robot",
      category: "ai",
      description: "AI model invocation with prompt template.",
      inputs: [
        { name: "prompt", label: "Prompt", type: "string", required: true },
        { name: "system_prompt", label: "System Prompt", type: "string", required: false },
        { name: "context", label: "Context", type: "string", required: false }
      ],
      outputs: [
        { name: "output", label: "Output", type: "string", required: false },
        { name: "usage", label: "Token Usage", type: "object", required: false }
      ],
      defaultConfig: {
        model: "gpt-4o-mini",
        provider: "openai",
        temperature: 0.7,
        max_tokens: 2048,
        system_prompt: "",
        use_memory: false
      }
    };
  }
  async run(inputs, config, _pool, _context) {
    const cfg = config;
    const prompt = String(inputs.prompt || cfg.prompt || "");
    const systemPrompt = String(inputs.system_prompt || cfg.system_prompt || "");
    const context = inputs.context ? String(inputs.context) : "";
    if (!prompt) {
      throw new NodeExecutionError(_context.nodeId, this.type, "Prompt is required");
    }
    const messages = [];
    if (systemPrompt) {
      messages.push({ role: "system", content: systemPrompt });
    }
    if (context) {
      messages.push({ role: "system", content: `Context:
${context}` });
    }
    messages.push({ role: "user", content: prompt });
    try {
      const result = await window.api.ai.chat(messages, {
        model: cfg.model,
        provider: cfg.provider
      });
      return { output: result, usage: {} };
    } catch (error) {
      const message = error instanceof Error ? error.message : "LLM call failed";
      throw new NodeExecutionError(_context.nodeId, this.type, message, { cause: error });
    }
  }
}
class Sandbox {
  constructor(config) {
    this.destroyed = false;
    this.id = nanoid.nanoid(10);
    this.workflowId = config.workflowId;
    this.runId = config.runId || nanoid.nanoid(10);
    this.rootPath = "";
    this.env = { ...config.env };
    this.allowedCommands = config.allowedCommands || [];
  }
  async create() {
    const fs = await import("fs/promises");
    const os = await import("os");
    const path2 = await import("path");
    const baseDir = path2.join(os.tmpdir(), "evolux-sandboxes", this.workflowId, this.runId);
    await fs.mkdir(baseDir, { recursive: true });
    await fs.mkdir(path2.join(baseDir, "src"), { recursive: true });
    await fs.mkdir(path2.join(baseDir, "output"), { recursive: true });
    await fs.mkdir(path2.join(baseDir, "temp"), { recursive: true });
    this.rootPath = baseDir;
  }
  async destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    try {
      const fs = await import("fs/promises");
      await fs.rm(this.rootPath, { recursive: true, force: true });
    } catch {
    }
  }
  // Filesystem operations
  async readFile(filePath) {
    this.assertNotDestroyed();
    const fs = await import("fs/promises");
    const fullPath = this.resolvePath(filePath);
    return fs.readFile(fullPath, "utf-8");
  }
  async writeFile(filePath, content) {
    this.assertNotDestroyed();
    const fs = await import("fs/promises");
    const path2 = await import("path");
    const fullPath = this.resolvePath(filePath);
    await fs.mkdir(path2.dirname(fullPath), { recursive: true });
    await fs.writeFile(fullPath, content, "utf-8");
  }
  async listDir(dirPath = "") {
    this.assertNotDestroyed();
    const fs = await import("fs/promises");
    const fullPath = this.resolvePath(dirPath);
    return fs.readdir(fullPath);
  }
  async exists(filePath) {
    try {
      const fs = await import("fs/promises");
      await fs.access(this.resolvePath(filePath));
      return true;
    } catch {
      return false;
    }
  }
  async stat(filePath) {
    this.assertNotDestroyed();
    const fs = await import("fs/promises");
    const s = await fs.stat(this.resolvePath(filePath));
    return { size: s.size, isFile: s.isFile(), isDir: s.isDirectory() };
  }
  async deleteFile(filePath) {
    this.assertNotDestroyed();
    const fs = await import("fs/promises");
    await fs.unlink(this.resolvePath(filePath));
  }
  // Process execution
  async exec(command, options = {}) {
    this.assertNotDestroyed();
    this.checkCommandAllowed(command);
    const { execFile } = await import("child_process");
    const { promisify } = await import("util");
    const execFileAsync2 = promisify(execFile);
    const timeoutMs = options.timeoutMs || 3e4;
    const maxBuffer = options.maxBuffer || 10 * 1024 * 1024;
    const startTime = Date.now();
    try {
      const isWin = process.platform === "win32";
      const shell = isWin ? "cmd.exe" : "/bin/sh";
      const shellArgs = isWin ? ["/c", command] : ["-c", command];
      const { stdout, stderr } = await execFileAsync2(shell, shellArgs, {
        cwd: options.cwd || this.rootPath,
        env: { ...process.env, ...this.env, ...options.env },
        timeout: timeoutMs,
        maxBuffer
      });
      return {
        stdout: stdout?.toString() || "",
        stderr: stderr?.toString() || "",
        exitCode: 0,
        durationMs: Date.now() - startTime
      };
    } catch (error) {
      const err = error;
      return {
        stdout: err.stdout?.toString() || "",
        stderr: err.stderr?.toString() || err.message || "Command failed",
        exitCode: err.code ?? 1,
        durationMs: Date.now() - startTime
      };
    }
  }
  async execCode(language, code, input) {
    this.assertNotDestroyed();
    const path2 = await import("path");
    const lang = language === "js" ? "javascript" : language === "py" ? "python" : language;
    const ext = lang === "python" ? ".py" : ".js";
    const fileName = `script_${nanoid.nanoid(6)}${ext}`;
    const filePath = path2.join(this.rootPath, "temp", fileName);
    await this.writeFile(`temp/${fileName}`, code);
    let command;
    if (lang === "python") {
      command = `python ${filePath}`;
    } else {
      command = `node ${filePath}`;
    }
    const result = await this.exec(command, {
      timeoutMs: 3e4,
      env: input ? { EVOLUX_INPUT: input } : void 0
    });
    try {
      await this.deleteFile(`temp/${fileName}`);
    } catch {
    }
    return result;
  }
  // Environment
  setEnv(key, value) {
    this.env[key] = value;
  }
  getEnv(key) {
    return this.env[key];
  }
  getAllEnv() {
    return { ...this.env };
  }
  // Snapshot
  async snapshot() {
    this.assertNotDestroyed();
    const fs = await import("fs/promises");
    const path2 = await import("path");
    const files = [];
    async function walk(dir, relativeTo) {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path2.join(dir, entry.name);
        const relPath = path2.relative(relativeTo, fullPath);
        if (entry.isDirectory()) {
          await walk(fullPath, relativeTo);
        } else {
          try {
            const content = await fs.readFile(fullPath, "utf-8");
            files.push({ path: relPath, content });
          } catch {
          }
        }
      }
    }
    await walk(this.rootPath, this.rootPath);
    return {
      id: nanoid.nanoid(10),
      files,
      env: { ...this.env },
      createdAt: Date.now()
    };
  }
  async restore(snapshot) {
    this.assertNotDestroyed();
    for (const file of snapshot.files) {
      await this.writeFile(file.path, file.content);
    }
    this.env = { ...snapshot.env };
  }
  // Helpers
  resolvePath(filePath) {
    const path2 = require("path");
    const resolved = path2.resolve(this.rootPath, filePath);
    if (!resolved.startsWith(this.rootPath)) {
      throw new Error(`Path traversal detected: ${filePath}`);
    }
    return resolved;
  }
  assertNotDestroyed() {
    if (this.destroyed) throw new Error("Sandbox has been destroyed");
  }
  checkCommandAllowed(command) {
    if (this.allowedCommands.length === 0) return;
    const cmd = command.trim().split(/\s+/)[0];
    if (!this.allowedCommands.includes(cmd)) {
      throw new Error(`Command not allowed: ${cmd}. Allowed: ${this.allowedCommands.join(", ")}`);
    }
  }
}
const activeSandboxes = /* @__PURE__ */ new Map();
async function createSandbox(config) {
  const key = `${config.workflowId}:${config.runId || "default"}`;
  if (activeSandboxes.has(key)) {
    return activeSandboxes.get(key);
  }
  const sandbox = new Sandbox(config);
  await sandbox.create();
  activeSandboxes.set(key, sandbox);
  return sandbox;
}
function getSandbox(workflowId, runId) {
  const key = `${workflowId}:${"default"}`;
  return activeSandboxes.get(key);
}
async function destroySandbox(workflowId, runId) {
  const key = `${workflowId}:${runId || "default"}`;
  const sandbox = activeSandboxes.get(key);
  if (sandbox) {
    await sandbox.destroy();
    activeSandboxes.delete(key);
  }
}
async function execCodeFallback(language, code) {
  {
    try {
      const fn = new Function("input", code);
      const result = fn("");
      return { stdout: String(result ?? ""), stderr: "" };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      return { stdout: "", stderr: message };
    }
  }
  return { stdout: "", stderr: `Sandbox not available for ${language}. Will be implemented in F8.` };
}
class CodeNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "code";
  }
  getMetadata() {
    return {
      type: "code",
      label: "Code",
      icon: "code-sandbox",
      category: "tools",
      description: "Execute Python or JavaScript code in sandbox.",
      inputs: [
        { name: "code", label: "Code", type: "string", required: true },
        { name: "input", label: "Input", type: "string", required: false }
      ],
      outputs: [
        { name: "output", label: "Output", type: "string", required: false },
        { name: "error", label: "Error", type: "string", required: false }
      ],
      defaultConfig: { language: "python", code: "" }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const code = String(inputs.code || cfg.code || "");
    const language = cfg.language || "python";
    const input = String(inputs.input || "");
    if (!code) {
      throw new NodeExecutionError(context.nodeId, this.type, "Code is required");
    }
    try {
      const sandbox = await createSandbox({ workflowId: context.nodeId, runId: `code-${context.nodeId}` });
      const result = await sandbox.execCode(language, code, input || void 0);
      return {
        output: result.stdout,
        error: result.stderr || ""
      };
    } catch (error) {
      if (language === "javascript") {
        const result = await execCodeFallback("javascript", code);
        return { output: result.stdout, error: result.stderr };
      }
      const message = error instanceof Error ? error.message : "Code execution failed";
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error });
    }
  }
}
class ConditionNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "condition";
  }
  getMetadata() {
    return {
      type: "condition",
      label: "Condition",
      icon: "branches",
      category: "logic",
      description: "IF/ELSE branching based on boolean expression.",
      inputs: [
        { name: "value", label: "Value", type: "string", required: true }
      ],
      outputs: [
        { name: "true_branch", label: "True", type: "string", required: false },
        { name: "false_branch", label: "False", type: "string", required: false },
        { name: "result", label: "Result", type: "boolean", required: false }
      ],
      defaultConfig: { expression: "", true_label: "Yes", false_label: "No" }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const value = inputs.value;
    const expr = cfg.expression || "";
    let result = false;
    if (expr) {
      try {
        const fn = new Function("value", `return ${expr}`);
        result = Boolean(fn(value));
      } catch (error) {
        const message = error instanceof Error ? error.message : "Expression evaluation failed";
        throw new NodeExecutionError(context.nodeId, this.type, `Invalid expression: ${message}`, { cause: error });
      }
    } else {
      result = Boolean(value);
    }
    return {
      true_branch: result ? String(value) : "",
      false_branch: result ? "" : String(value),
      result
    };
  }
}
class HTTPRequestNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "http-request";
  }
  getMetadata() {
    return {
      type: "http-request",
      label: "HTTP Request",
      icon: "global",
      category: "tools",
      description: "Make external HTTP API calls.",
      inputs: [
        { name: "url", label: "URL", type: "string", required: true },
        { name: "body", label: "Body", type: "string", required: false }
      ],
      outputs: [
        { name: "response", label: "Response", type: "string", required: false },
        { name: "status", label: "Status Code", type: "number", required: false },
        { name: "headers", label: "Response Headers", type: "object", required: false }
      ],
      defaultConfig: { method: "GET", url: "", headers: {}, timeout_ms: 3e4 }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const url = String(inputs.url || cfg.url || "");
    const method = cfg.method || "GET";
    const headers = cfg.headers || {};
    const body = inputs.body ?? cfg.body;
    const timeoutMs = cfg.timeout_ms || 3e4;
    if (!url) {
      throw new NodeExecutionError(context.nodeId, this.type, "URL is required");
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json", ...headers },
        body: body ? typeof body === "string" ? body : JSON.stringify(body) : void 0,
        signal: controller.signal
      });
      const responseText = await response.text();
      let responseData = responseText;
      try {
        responseData = JSON.parse(responseText);
      } catch {
      }
      const responseHeaders = {};
      response.headers.forEach((value, key) => {
        responseHeaders[key] = value;
      });
      return {
        response: typeof responseData === "string" ? responseData : JSON.stringify(responseData, null, 2),
        status: response.status,
        headers: responseHeaders
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : "HTTP request failed";
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error });
    } finally {
      clearTimeout(timeout);
    }
  }
}
class TemplateNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "template";
  }
  getMetadata() {
    return {
      type: "template",
      label: "Template",
      icon: "file-text",
      category: "logic",
      description: "Render a template string with variable substitution.",
      inputs: [
        { name: "template", label: "Template", type: "string", required: true }
      ],
      outputs: [
        { name: "output", label: "Output", type: "string", required: false }
      ],
      defaultConfig: { template: "" }
    };
  }
  async run(inputs, config, pool, _context) {
    const cfg = config;
    const template = String(inputs.template || cfg.template || "");
    const output = resolveTemplate(template, pool);
    return { output };
  }
}
class IterationNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "iteration";
  }
  getMetadata() {
    return {
      type: "iteration",
      label: "Iteration",
      icon: "reload",
      category: "logic",
      description: "For-each loop over an array. Processes each item.",
      inputs: [
        { name: "array", label: "Array", type: "array", required: true },
        { name: "item_handler", label: "Item Handler", type: "string", required: false }
      ],
      outputs: [
        { name: "results", label: "Results", type: "array", required: false },
        { name: "current_item", label: "Last Item", type: "string", required: false },
        { name: "index", label: "Last Index", type: "number", required: false },
        { name: "count", label: "Total Count", type: "number", required: false }
      ],
      defaultConfig: { max_iterations: 100 }
    };
  }
  async run(inputs, config, pool, context) {
    const cfg = config;
    const maxIterations = cfg.max_iterations || 100;
    let array;
    if (Array.isArray(inputs.array)) {
      array = inputs.array;
    } else if (typeof inputs.array === "string") {
      try {
        const parsed = JSON.parse(inputs.array);
        if (!Array.isArray(parsed)) {
          throw new NodeExecutionError(context.nodeId, this.type, "Input is not a valid JSON array");
        }
        array = parsed;
      } catch (error) {
        if (error instanceof NodeExecutionError) throw error;
        throw new NodeExecutionError(context.nodeId, this.type, "Failed to parse array input", { cause: error });
      }
    } else {
      throw new NodeExecutionError(context.nodeId, this.type, "Array input is required");
    }
    const limit = Math.min(array.length, maxIterations);
    const results = [];
    for (let i = 0; i < limit; i++) {
      const item = array[i];
      pool.set([context.nodeId, "current_item"], item);
      pool.set([context.nodeId, "index"], i);
      const handler = String(inputs.item_handler || "");
      if (handler) {
        pool.set([context.nodeId, "_item"], item);
        pool.set([context.nodeId, "_index"], i);
      }
      results.push(item);
    }
    return {
      results,
      current_item: limit > 0 ? String(array[limit - 1]) : "",
      index: limit - 1,
      count: limit
    };
  }
}
class LoopNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "loop";
  }
  getMetadata() {
    return {
      type: "loop",
      label: "Loop",
      icon: "sync",
      category: "logic",
      description: "While loop with condition. Max iterations safety limit.",
      inputs: [
        { name: "value", label: "Value", type: "string", required: true }
      ],
      outputs: [
        { name: "output", label: "Final Output", type: "string", required: false },
        { name: "iterations", label: "Iterations", type: "number", required: false }
      ],
      defaultConfig: { condition: "", max_iterations: 100 }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const maxIterations = cfg.max_iterations || 100;
    const condition = cfg.condition || "";
    if (!condition) {
      return { output: inputs.value, iterations: 0 };
    }
    let iterations = 0;
    let currentValue = inputs.value;
    while (iterations < maxIterations) {
      let result = false;
      try {
        const fn = new Function("value", "iteration", `return ${condition}`);
        result = Boolean(fn(currentValue, iterations));
      } catch (error) {
        const message = error instanceof Error ? error.message : "Condition evaluation failed";
        throw new NodeExecutionError(context.nodeId, this.type, `Invalid condition: ${message}`, { cause: error });
      }
      if (!result) break;
      iterations++;
    }
    if (iterations >= maxIterations) {
      throw new NodeExecutionError(context.nodeId, this.type, `Loop exceeded max iterations: ${maxIterations}`);
    }
    return { output: currentValue, iterations };
  }
}
class VariableAggregatorNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "variable-aggregator";
  }
  getMetadata() {
    return {
      type: "variable-aggregator",
      label: "Variable Aggregator",
      icon: "merge-cells",
      category: "logic",
      description: "Merge variables from parallel branches into single output.",
      inputs: [
        { name: "value_a", label: "Value A", type: "string", required: false },
        { name: "value_b", label: "Value B", type: "string", required: false }
      ],
      outputs: [
        { name: "output", label: "Merged Output", type: "string", required: false }
      ],
      defaultConfig: { mode: "concat" }
    };
  }
  async run(inputs, config, _pool, _context) {
    const cfg = config;
    const mode = cfg.mode || "concat";
    const values = Object.values(inputs).filter((v) => v !== void 0 && v !== null && v !== "");
    if (values.length === 0) return { output: "" };
    if (mode === "first") return { output: String(values[0]) };
    if (mode === "array") return { output: JSON.stringify(values) };
    return { output: values.map((v) => String(v)).join("\n") };
  }
}
class VariableAssignerNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "variable-assigner";
  }
  getMetadata() {
    return {
      type: "variable-assigner",
      label: "Variable Assigner",
      icon: "edit",
      category: "logic",
      description: "Set or overwrite a variable value at runtime.",
      inputs: [
        { name: "value", label: "Value", type: "string", required: true }
      ],
      outputs: [
        { name: "output", label: "Output", type: "string", required: false }
      ],
      defaultConfig: { variable_name: "", value: "" }
    };
  }
  async run(inputs, config, pool, context) {
    const cfg = config;
    const value = inputs.value ?? cfg.value ?? "";
    const varName = cfg.variable_name || "output";
    pool.set([context.nodeId, varName], value);
    return { output: value };
  }
}
class MemoryGraph {
  constructor() {
    this.semantic = /* @__PURE__ */ new Map();
    this.episodic = /* @__PURE__ */ new Map();
    this.procedural = /* @__PURE__ */ new Map();
    this.edges = [];
  }
  // Semantic
  addSemantic(unit) {
    const id = nanoid.nanoid(10);
    this.semantic.set(id, { ...unit, id, createdAt: Date.now(), accessCount: 0 });
    return id;
  }
  getSemantic(id) {
    const unit = this.semantic.get(id);
    if (unit) unit.accessCount++;
    return unit;
  }
  getAllSemantic() {
    return Array.from(this.semantic.values());
  }
  removeSemantic(id) {
    this.semantic.delete(id);
    this.edges = this.edges.filter((e) => e.sourceId !== id && e.targetId !== id);
  }
  // Episodic
  addEpisode(unit) {
    const id = nanoid.nanoid(10);
    this.episodic.set(id, { ...unit, id, createdAt: Date.now() });
    return id;
  }
  getEpisode(id) {
    return this.episodic.get(id);
  }
  getAllEpisodes() {
    return Array.from(this.episodic.values());
  }
  getSuccessfulEpisodes() {
    return this.getAllEpisodes().filter((e) => e.outcome === "success");
  }
  // Procedural
  addProcedure(unit) {
    const id = nanoid.nanoid(10);
    this.procedural.set(id, { ...unit, id, createdAt: Date.now(), lastUsedAt: Date.now() });
    return id;
  }
  getProcedure(id) {
    const proc = this.procedural.get(id);
    if (proc) {
      proc.usageCount++;
      proc.lastUsedAt = Date.now();
    }
    return proc;
  }
  getAllProcedures() {
    return Array.from(this.procedural.values());
  }
  // Edges
  addEdge(sourceId, targetId, type, weight = 1) {
    const id = nanoid.nanoid(10);
    this.edges.push({ id, sourceId, targetId, type, weight, createdAt: Date.now() });
    return id;
  }
  getEdgesFrom(sourceId) {
    return this.edges.filter((e) => e.sourceId === sourceId);
  }
  getEdgesTo(targetId) {
    return this.edges.filter((e) => e.targetId === targetId);
  }
  removeEdge(id) {
    this.edges = this.edges.filter((e) => e.id !== id);
  }
  // Stats
  getStats() {
    return {
      semanticCount: this.semantic.size,
      episodicCount: this.episodic.size,
      proceduralCount: this.procedural.size,
      edgeCount: this.edges.length
    };
  }
  // Serialization
  toJSON() {
    return {
      semantic: Array.from(this.semantic.values()).map((u) => ({ ...u, embedding: void 0 })),
      episodic: Array.from(this.episodic.values()).map((u) => ({ ...u, embedding: void 0 })),
      procedural: Array.from(this.procedural.values()).map((u) => ({ ...u, embedding: void 0 })),
      edges: this.edges
    };
  }
}
const MODEL = "Xenova/multilingual-e5-small";
const DIMENSION = 384;
let embedder = null;
function createFallbackEmbedder() {
  return async (_input) => {
    const arr = new Float32Array(DIMENSION);
    for (let i = 0; i < DIMENSION; i++) {
      arr[i] = Math.random() * 2 - 1;
    }
    let norm = 0;
    for (let i = 0; i < DIMENSION; i++) norm += arr[i] * arr[i];
    norm = Math.sqrt(norm);
    if (norm > 0) {
      for (let i = 0; i < DIMENSION; i++) arr[i] /= norm;
    }
    return { data: arr };
  };
}
async function getEmbedder() {
  if (!embedder) {
    try {
      const mod = require("@xenova/transformers");
      const pipelineFn = mod.pipeline;
      embedder = await pipelineFn("feature-extraction", MODEL);
    } catch {
      embedder = createFallbackEmbedder();
    }
  }
  return embedder;
}
async function embed(text, mode = "passage") {
  const pipe = await getEmbedder();
  const input = mode === "query" ? `query: ${text}` : `passage: ${text}`;
  const output = await pipe(input, { pooling: "mean", normalize: true });
  return output.data;
}
function cosineSimilarity(a, b) {
  let dot = 0;
  let normA = 0;
  let normB = 0;
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  const denom = Math.sqrt(normA) * Math.sqrt(normB);
  return denom === 0 ? 0 : dot / denom;
}
class SemanticLayer {
  constructor(graph) {
    this.graph = graph;
  }
  async add(content, type, metadata = {}) {
    const embedding = await embed(content, "passage");
    return this.graph.addSemantic({ type, content, embedding, metadata });
  }
  async search(query, k = 5) {
    const queryEmbedding = await embed(query, "query");
    const units = this.graph.getAllSemantic();
    const scored = [];
    for (const unit of units) {
      if (!unit.embedding) continue;
      const score = cosineSimilarity(queryEmbedding, unit.embedding);
      scored.push({ unit, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, k);
  }
  async addBatch(items) {
    const ids = [];
    for (const item of items) {
      const id = await this.add(item.content, item.type, item.metadata);
      ids.push(id);
    }
    return ids;
  }
  getByType(type) {
    return this.graph.getAllSemantic().filter((u) => u.type === type);
  }
  getMostAccessed(limit) {
    return this.graph.getAllSemantic().sort((a, b) => b.accessCount - a.accessCount).slice(0, limit);
  }
}
class EpisodicLayer {
  constructor(graph) {
    this.graph = graph;
  }
  async recordEpisode(runId, taskDescription, trajectory, outcome, feedback) {
    const embedding = await embed(taskDescription, "passage");
    return this.graph.addEpisode({
      runId,
      taskDescription,
      trajectory,
      outcome,
      feedback,
      embedding
    });
  }
  async search(query, k = 5) {
    const queryEmbedding = await embed(query, "query");
    const episodes = this.graph.getAllEpisodes();
    const scored = [];
    for (const episode of episodes) {
      if (!episode.embedding) continue;
      const score = cosineSimilarity(queryEmbedding, episode.embedding);
      scored.push({ episode, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, k);
  }
  getSuccessful() {
    return this.graph.getSuccessfulEpisodes();
  }
  getByRunId(runId) {
    return this.graph.getAllEpisodes().filter((e) => e.runId === runId);
  }
  getRecent(limit) {
    return this.graph.getAllEpisodes().sort((a, b) => b.createdAt - a.createdAt).slice(0, limit);
  }
}
class ProceduralLayer {
  constructor(graph) {
    this.graph = graph;
  }
  async distill(name, description, pattern, sourceEpisodes) {
    const embedding = await embed(`${name}: ${description}`, "passage");
    const episodes = sourceEpisodes.map((id) => this.graph.getEpisode(id)).filter((e) => e !== void 0);
    const successCount = episodes.filter((e) => e.outcome === "success").length;
    const successRate = episodes.length > 0 ? successCount / episodes.length : 0;
    return this.graph.addProcedure({
      name,
      description,
      pattern,
      sourceEpisodes,
      usageCount: 0,
      successRate,
      maturityScore: this.calculatePEMS(0, successRate, episodes.length),
      embedding
    });
  }
  async search(query, k = 5) {
    const queryEmbedding = await embed(query, "query");
    const procedures = this.graph.getAllProcedures();
    const scored = [];
    for (const proc of procedures) {
      if (!proc.embedding) continue;
      const score = cosineSimilarity(queryEmbedding, proc.embedding);
      scored.push({ procedure: proc, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, k);
  }
  getMature(threshold = 0.5) {
    return this.graph.getAllProcedures().filter((p) => p.maturityScore >= threshold);
  }
  getMostUsed(limit) {
    return this.graph.getAllProcedures().sort((a, b) => b.usageCount - a.usageCount).slice(0, limit);
  }
  calculatePEMS(usageCount, successRate, episodeCount) {
    const usageScore = Math.min(usageCount / 10, 1);
    const stabilityScore = successRate;
    const experienceScore = Math.min(episodeCount / 5, 1);
    return usageScore * 0.3 + stabilityScore * 0.5 + experienceScore * 0.2;
  }
}
class StageOneConnection {
  constructor(graph) {
    this.graph = graph;
    this.semantic = new SemanticLayer(graph);
    this.episodic = new EpisodicLayer(graph);
    this.procedural = new ProceduralLayer(graph);
  }
  async getContext(observation, k = 5) {
    const [semanticResults, episodicResults, proceduralResults] = await Promise.all([
      this.semantic.search(observation, k),
      this.episodic.search(observation, k),
      this.procedural.search(observation, k)
    ]);
    const semantic = semanticResults.map((r) => r.unit);
    const episodic = episodicResults.map((r) => r.episode);
    const procedural = proceduralResults.map((r) => r.procedure);
    const parts = [];
    if (semantic.length > 0) {
      parts.push("## Relevant Knowledge");
      for (const unit of semantic) {
        parts.push(`- [${unit.type}] ${unit.content}`);
      }
    }
    if (episodic.length > 0) {
      parts.push("## Similar Past Experiences");
      for (const ep of episodic) {
        const outcome = ep.outcome === "success" ? "✓" : "✗";
        parts.push(`- ${outcome} ${ep.taskDescription.substring(0, 200)}`);
        if (ep.feedback) parts.push(`  Feedback: ${ep.feedback.substring(0, 200)}`);
      }
    }
    if (procedural.length > 0) {
      parts.push("## Known Patterns");
      for (const proc of procedural) {
        parts.push(`- ${proc.name}: ${proc.description}`);
        parts.push(`  Pattern: ${proc.pattern.substring(0, 300)}`);
      }
    }
    return {
      semantic,
      episodic,
      procedural,
      formatted: parts.join("\n")
    };
  }
  getLayers() {
    return {
      semantic: this.semantic,
      episodic: this.episodic,
      procedural: this.procedural
    };
  }
}
class StageTwoRefinement {
  constructor(graph) {
    this.graph = graph;
    this.semantic = new SemanticLayer(graph);
  }
  async refine(feedback) {
    const result = { edgesAdded: 0, edgesRemoved: 0, contentReshaped: 0 };
    const underConnection = await this.fixUnderConnection(feedback);
    result.edgesAdded = underConnection;
    const overConnection = this.fixOverConnection();
    result.edgesRemoved = overConnection;
    const reshaped = await this.reshapeContent(feedback);
    result.contentReshaped = reshaped;
    return result;
  }
  async fixUnderConnection(feedback) {
    const searchResults = await this.semantic.search(feedback, 10);
    let added = 0;
    for (let i = 0; i < searchResults.length; i++) {
      for (let j = i + 1; j < searchResults.length; j++) {
        const a = searchResults[i];
        const b = searchResults[j];
        if (a.score > 0.7 && b.score > 0.7) {
          const existingEdges = this.graph.getEdgesFrom(a.unit.id);
          const alreadyConnected = existingEdges.some((e) => e.targetId === b.unit.id);
          if (!alreadyConnected) {
            this.graph.addEdge(a.unit.id, b.unit.id, "refine", a.score);
            added++;
          }
        }
      }
    }
    return added;
  }
  fixOverConnection() {
    const allEdges = [];
    const semanticUnits = this.graph.getAllSemantic();
    for (const unit of semanticUnits) {
      allEdges.push(...this.graph.getEdgesFrom(unit.id));
    }
    let removed = 0;
    for (const edge of allEdges) {
      if (edge.weight < 0.3) {
        this.graph.removeEdge(edge.id);
        removed++;
      }
    }
    return removed;
  }
  async reshapeContent(feedback) {
    const feedbackWords = feedback.toLowerCase().split(/\s+/);
    const needsMoreDetail = feedbackWords.some((w) => ["brief", "short", "missing", "incomplete", "more detail"].includes(w));
    const needsCompression = feedbackWords.some((w) => ["verbose", "long", "redundant", "too much", "summarize"].includes(w));
    if (!needsMoreDetail && !needsCompression) return 0;
    const units = this.graph.getAllSemantic();
    let reshaped = 0;
    for (const unit of units) {
      if (needsMoreDetail && unit.content.length < 100) {
        unit.metadata["needsExpansion"] = true;
        reshaped++;
      }
      if (needsCompression && unit.content.length > 1e3) {
        unit.metadata["needsCompression"] = true;
        reshaped++;
      }
    }
    return reshaped;
  }
}
class StageThreeConsolidation {
  constructor(graph) {
    this.graph = graph;
    this.procedural = new ProceduralLayer(graph);
  }
  async consolidate() {
    const successfulEpisodes = this.graph.getSuccessfulEpisodes();
    if (successfulEpisodes.length < 2) {
      return { clustersFormed: 0, proceduresDistilled: 0, matureProcedures: 0 };
    }
    const clusters = this.clusterEpisodes(successfulEpisodes);
    let proceduresDistilled = 0;
    for (const cluster of clusters) {
      if (cluster.length >= 2) {
        const pattern = this.extractPattern(cluster);
        if (pattern) {
          await this.procedural.distill(
            `Pattern from ${cluster.length} episodes`,
            pattern.summary,
            pattern.template,
            cluster.map((e) => e.id)
          );
          proceduresDistilled++;
        }
      }
    }
    const matureProcedures = this.procedural.getMature(0.5).length;
    return {
      clustersFormed: clusters.length,
      proceduresDistilled,
      matureProcedures
    };
  }
  clusterEpisodes(episodes) {
    const clusters = [];
    const assigned = /* @__PURE__ */ new Set();
    for (const episode of episodes) {
      if (assigned.has(episode.id)) continue;
      const cluster = [episode];
      assigned.add(episode.id);
      for (const other of episodes) {
        if (assigned.has(other.id)) continue;
        if (this.areSimilar(episode, other)) {
          cluster.push(other);
          assigned.add(other.id);
        }
      }
      clusters.push(cluster);
    }
    return clusters;
  }
  areSimilar(a, b) {
    const aWords = new Set(a.taskDescription.toLowerCase().split(/\s+/));
    const bWords = new Set(b.taskDescription.toLowerCase().split(/\s+/));
    let overlap = 0;
    for (const word of aWords) {
      if (bWords.has(word) && word.length > 3) overlap++;
    }
    const minSize = Math.min(aWords.size, bWords.size);
    return minSize > 0 ? overlap / minSize > 0.3 : false;
  }
  extractPattern(cluster) {
    if (cluster.length === 0) return null;
    const commonSteps = [];
    const minLength = Math.min(...cluster.map((e) => e.trajectory.length));
    for (let i = 0; i < minLength; i++) {
      const actions = cluster.map((e) => e.trajectory[i]?.action || "");
      const allSame = actions.every((a) => a === actions[0]);
      if (allSame && actions[0]) {
        commonSteps.push(actions[0]);
      }
    }
    if (commonSteps.length === 0) return null;
    return {
      summary: `Common pattern from ${cluster.length} successful runs`,
      template: commonSteps.join(" → ")
    };
  }
}
class WorkflowMemory {
  constructor(runId) {
    this.currentTrajectory = [];
    this.graph = new MemoryGraph();
    this.semantic = new SemanticLayer(this.graph);
    this.episodic = new EpisodicLayer(this.graph);
    this.procedural = new ProceduralLayer(this.graph);
    this.stage1 = new StageOneConnection(this.graph);
    this.stage2 = new StageTwoRefinement(this.graph);
    this.stage3 = new StageThreeConsolidation(this.graph);
    this.currentRunId = runId || `run-${Date.now()}`;
  }
  // Stage I: Get context for current step
  async getContext(observation, k = 5) {
    return this.stage1.getContext(observation, k);
  }
  // Stage II: Refine based on feedback
  async refine(feedback) {
    return this.stage2.refine(feedback);
  }
  // Stage III: Consolidate after run
  async consolidate() {
    return this.stage3.consolidate();
  }
  // Record a step in current trajectory
  recordStep(step) {
    this.currentTrajectory.push(step);
  }
  // Record outcome of current run
  async recordOutcome(outcome, feedback) {
    return this.episodic.recordEpisode(
      this.currentRunId,
      this.currentTrajectory.map((s) => s.action).join(" → "),
      this.currentTrajectory,
      outcome,
      feedback
    );
  }
  // Add semantic knowledge
  async addSemantic(content, type, metadata) {
    return this.semantic.add(content, type, metadata);
  }
  // Search semantic memory
  async searchSemantic(query, k = 5) {
    return this.semantic.search(query, k);
  }
  // Search episodic memory
  async searchEpisodic(query, k = 5) {
    return this.episodic.search(query, k);
  }
  // Search procedural memory
  async searchProcedural(query, k = 5) {
    return this.procedural.search(query, k);
  }
  // Get stats
  getStats() {
    return this.graph.getStats();
  }
  // Serialize
  toJSON() {
    return this.graph.toJSON();
  }
}
const memoryInstances = /* @__PURE__ */ new Map();
function getOrCreateMemory(workflowId) {
  if (!memoryInstances.has(workflowId)) {
    memoryInstances.set(workflowId, new WorkflowMemory(workflowId));
  }
  return memoryInstances.get(workflowId);
}
class KnowledgeRetrievalNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "knowledge-retrieval";
  }
  getMetadata() {
    return {
      type: "knowledge-retrieval",
      label: "Knowledge Retrieval",
      icon: "database",
      category: "ai",
      description: "Query workflow memory graph (FluxMem) for relevant context.",
      inputs: [
        { name: "query", label: "Query", type: "string", required: true }
      ],
      outputs: [
        { name: "results", label: "Results", type: "string", required: false },
        { name: "count", label: "Result Count", type: "number", required: false }
      ],
      defaultConfig: { top_k: 5, layer: "all" }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const query = String(inputs.query || cfg.query || "");
    const topK = cfg.top_k || 5;
    const layer = cfg.layer || "all";
    if (!query) {
      return { results: "", count: 0 };
    }
    const memory = getOrCreateMemory(context.nodeId);
    const parts = [];
    if (layer === "all" || layer === "semantic") {
      const semanticResults = await memory.searchSemantic(query, topK);
      if (semanticResults.length > 0) {
        parts.push("## Relevant Knowledge");
        for (const r of semanticResults) {
          parts.push(`- [${r.unit.type}] ${r.unit.content} (score: ${r.score.toFixed(2)})`);
        }
      }
    }
    if (layer === "all" || layer === "episodic") {
      const episodicResults = await memory.searchEpisodic(query, topK);
      if (episodicResults.length > 0) {
        parts.push("## Similar Past Experiences");
        for (const r of episodicResults) {
          const outcome = r.episode.outcome === "success" ? "✓" : "✗";
          parts.push(`- ${outcome} ${r.episode.taskDescription.substring(0, 200)} (score: ${r.score.toFixed(2)})`);
        }
      }
    }
    if (layer === "all" || layer === "procedural") {
      const proceduralResults = await memory.searchProcedural(query, topK);
      if (proceduralResults.length > 0) {
        parts.push("## Known Patterns");
        for (const r of proceduralResults) {
          parts.push(`- ${r.procedure.name}: ${r.procedure.description} (score: ${r.score.toFixed(2)})`);
        }
      }
    }
    const formatted = parts.join("\n");
    return { results: formatted, count: parts.filter((p) => p.startsWith("- ")).length };
  }
}
class ParameterExtractorNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "parameter-extractor";
  }
  getMetadata() {
    return {
      type: "parameter-extractor",
      label: "Parameter Extractor",
      icon: "scan",
      category: "ai",
      description: "LLM-powered structured parameter extraction from text.",
      inputs: [
        { name: "text", label: "Text", type: "string", required: true }
      ],
      outputs: [
        { name: "parameters", label: "Parameters", type: "object", required: false },
        { name: "raw", label: "Raw Output", type: "string", required: false }
      ],
      defaultConfig: { parameters: [], model: "gpt-4o-mini" }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const text = String(inputs.text || cfg.text || "");
    const params = cfg.parameters || [];
    if (!text) {
      throw new NodeExecutionError(context.nodeId, this.type, "Text input is required");
    }
    const paramDescriptions = params.map(
      (p) => `- ${p.name} (${p.type}): ${p.description || "No description"}`
    ).join("\n");
    const prompt = `Extract the following parameters from the text below. Return as JSON object.

Parameters:
${paramDescriptions}

Text:
${text}

Return ONLY a valid JSON object.`;
    try {
      const result = await window.api.ai.chat(
        [{ role: "user", content: prompt }],
        { model: cfg.model || "gpt-4o-mini" }
      );
      let extracted = {};
      try {
        const jsonMatch = result.match(/\{[\s\S]*\}/);
        if (jsonMatch) {
          extracted = JSON.parse(jsonMatch[0]);
        }
      } catch {
      }
      return { parameters: extracted, raw: result };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Parameter extraction failed";
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error });
    }
  }
}
class QuestionClassifierNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "question-classifier";
  }
  getMetadata() {
    return {
      type: "question-classifier",
      label: "Question Classifier",
      icon: "tags",
      category: "ai",
      description: "LLM-powered N-way classification of input text.",
      inputs: [
        { name: "text", label: "Text", type: "string", required: true }
      ],
      outputs: [
        { name: "category", label: "Category", type: "string", required: false },
        { name: "confidence", label: "Confidence", type: "number", required: false },
        { name: "raw", label: "Raw Output", type: "string", required: false }
      ],
      defaultConfig: { categories: [], model: "gpt-4o-mini" }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const text = String(inputs.text || "");
    const categories = cfg.categories || [];
    if (!text) {
      throw new NodeExecutionError(context.nodeId, this.type, "Text input is required");
    }
    if (categories.length === 0) {
      throw new NodeExecutionError(context.nodeId, this.type, "At least one category is required");
    }
    const prompt = `Classify the following text into one of these categories: ${categories.join(", ")}

Text: ${text}

Return ONLY the category name.`;
    try {
      const result = await window.api.ai.chat(
        [{ role: "user", content: prompt }],
        { model: cfg.model || "gpt-4o-mini" }
      );
      const category = result.trim();
      const matched = categories.find((c) => category.toLowerCase().includes(c.toLowerCase()));
      return {
        category: matched || category,
        confidence: matched ? 1 : 0.5,
        raw: result
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Classification failed";
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error });
    }
  }
}
const EXTENSION_MAP = {};
function reg(ext, category, opts = {}) {
  EXTENSION_MAP[ext.toLowerCase()] = {
    extension: ext,
    category,
    isBinary: false,
    parser: "plain",
    ...opts
  };
}
for (const ext of ["ts", "tsx", "js", "jsx", "py", "java", "go", "rs", "c", "cpp", "h", "hpp", "cs", "rb", "php", "swift", "kt", "lua", "sh", "bash", "bat", "ps1", "sql", "r", "scala", "dart", "zig", "nim", "ex", "exs", "hs", "ml", "clj", "lisp", "asm", "s"]) {
  reg(ext, "code", { language: ext });
}
for (const ext of ["html", "htm", "css", "scss", "sass", "less", "vue", "svelte", "astro"]) {
  reg(ext, "web", { language: ext });
}
for (const ext of ["json", "yaml", "yml", "toml", "ini", "env", "xml", "properties", "conf", "cfg", "editorconfig", "gitignore", "dockerignore", "eslintrc", "prettierrc"]) {
  reg(ext, "config");
}
for (const ext of ["md", "mdx"]) {
  reg(ext, "markdown", { parser: "markdown" });
}
reg("rst", "docs");
reg("tex", "docs");
reg("txt", "docs");
reg("log", "docs");
reg("diff", "docs");
reg("patch", "docs");
for (const ext of ["csv", "tsv"]) {
  reg(ext, "data", { parser: "csv" });
}
for (const ext of ["docx", "doc", "pptx", "ppt", "xlsx", "xls"]) {
  reg(ext, "office", { parser: "markitdown", isBinary: true });
}
reg("pdf", "pdf", { parser: "markitdown", isBinary: true });
for (const ext of ["png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "webp", "svg", "ico"]) {
  reg(ext, "image", { isBinary: true, parser: "markitdown" });
}
for (const ext of ["mp3", "wav", "flac", "ogg", "m4a"]) {
  reg(ext, "audio", { isBinary: true, parser: "markitdown" });
}
for (const ext of ["zip", "tar", "gz", "rar", "7z"]) {
  reg(ext, "archive", { isBinary: true, parser: "markitdown" });
}
for (const ext of ["exe", "dll", "so", "dylib", "wasm", "woff", "woff2", "ttf", "otf", "eot", "bin", "dat", "db", "sqlite", "sqlite3", "pyc", "class", "o", "obj"]) {
  reg(ext, "binary", { isBinary: true, parser: "skip" });
}
function detectFileType(filePath) {
  const ext = getExtension(filePath);
  return EXTENSION_MAP[ext] || {
    extension: ext,
    category: "unknown",
    isBinary: false,
    parser: "plain"
  };
}
function getExtension(filePath) {
  const parts = filePath.split(".");
  if (parts.length < 2) return "";
  return parts[parts.length - 1].toLowerCase();
}
function getFileName(filePath) {
  const parts = filePath.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || "";
}
function shouldSkipFile(filePath) {
  return detectFileType(filePath).parser === "skip";
}
function getLanguage(filePath) {
  const info = detectFileType(filePath);
  return info.language || info.category;
}
const DEFAULT_EXCLUDE$2 = ["node_modules", ".git", "dist", "out", ".next", "__pycache__", ".venv", "venv", ".cache", "coverage"];
class FileExplorerNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "file-explorer";
  }
  getMetadata() {
    return {
      type: "file-explorer",
      label: "File Explorer",
      icon: "folder-open",
      category: "tools",
      description: "Browse & select local files/folders. Filter by extension. Exclude patterns.",
      inputs: [
        { name: "root_path", label: "Root Path", type: "string", required: true }
      ],
      outputs: [
        { name: "files", label: "Files", type: "array", required: false },
        { name: "file_count", label: "File Count", type: "number", required: false },
        { name: "root_path", label: "Root Path", type: "string", required: false }
      ],
      defaultConfig: {
        file_types: [],
        exclude_patterns: DEFAULT_EXCLUDE$2,
        max_depth: 10,
        max_files: 1e3,
        include_hidden: false
      }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const rootPath = String(inputs.root_path || cfg.root_path || "");
    if (!rootPath) {
      throw new NodeExecutionError(context.nodeId, this.type, "Root path is required");
    }
    const fs = await import("fs/promises");
    const path2 = await import("path");
    const excludePatterns = cfg.exclude_patterns || DEFAULT_EXCLUDE$2;
    const maxDepth = cfg.max_depth || 10;
    const maxFiles = cfg.max_files || 1e3;
    const includeHidden = cfg.include_hidden || false;
    const fileTypes = (cfg.file_types || []).map((t) => t.startsWith(".") ? t.substring(1).toLowerCase() : t.toLowerCase());
    const files = [];
    async function scan(dirPath, depth) {
      if (depth > maxDepth || files.length >= maxFiles) return;
      let entries;
      try {
        entries = await fs.readdir(dirPath);
      } catch {
        return;
      }
      for (const entry of entries) {
        if (files.length >= maxFiles) break;
        if (!includeHidden && entry.startsWith(".")) continue;
        if (excludePatterns.includes(entry)) continue;
        const fullPath = path2.join(dirPath, entry);
        let stat;
        try {
          stat = await fs.stat(fullPath);
        } catch {
          continue;
        }
        if (stat.isDirectory()) {
          await scan(fullPath, depth + 1);
        } else {
          const ext = getExtension(entry);
          if (fileTypes.length > 0 && !fileTypes.includes(ext)) continue;
          const info = detectFileType(entry);
          files.push({
            path: fullPath,
            relativePath: path2.relative(rootPath, fullPath),
            name: entry,
            extension: ext,
            size: stat.size,
            modifiedAt: stat.mtimeMs,
            isBinary: info.isBinary,
            category: info.category,
            language: info.language
          });
        }
      }
    }
    await scan(rootPath, 0);
    return {
      files,
      file_count: files.length,
      root_path: rootPath
    };
  }
}
const MARKITDOWN_CATEGORIES = ["office", "pdf", "image", "audio", "archive", "web", "data"];
async function convertFile(filePath, options) {
  const info = detectFileType(filePath);
  const fileName = getFileName(filePath);
  if (info.parser === "skip") {
    return { content: `[Binary file: ${fileName}]`, convertedBy: "binary_skip" };
  }
  if (info.parser === "plain") {
    return readPlainText(filePath);
  }
  if (info.parser === "markdown") {
    return readPlainText(filePath);
  }
  if (info.parser === "csv") {
    return readPlainText(filePath);
  }
  if (info.parser === "markitdown" || options?.useMarkitdown && MARKITDOWN_CATEGORIES.includes(info.category)) {
    return convertViaMarkitdown(filePath);
  }
  return readPlainText(filePath);
}
async function readPlainText(filePath) {
  try {
    const fs = await import("fs/promises");
    const content = await fs.readFile(filePath, "utf-8");
    return { content, convertedBy: "plain_text" };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Read failed";
    return { content: `[Error reading file: ${message}]`, convertedBy: "plain_text" };
  }
}
async function convertViaMarkitdown(filePath) {
  try {
    const { execFile } = await import("child_process");
    const { promisify } = await import("util");
    const execFileAsync2 = promisify(execFile);
    const { stdout } = await execFileAsync2("markitdown", [filePath], {
      timeout: 3e4,
      maxBuffer: 50 * 1024 * 1024
    });
    return { content: stdout, convertedBy: "markitdown" };
  } catch {
    try {
      return await convertViaPython(filePath);
    } catch {
      return readPlainText(filePath);
    }
  }
}
async function convertViaPython(filePath) {
  const { execFile } = await import("child_process");
  const { promisify } = await import("util");
  const execFileAsync2 = promisify(execFile);
  const script = `
import sys
from markitdown import MarkItDown
md = MarkItDown()
result = md.convert(sys.argv[1])
print(result.text_content)
`;
  const { stdout } = await execFileAsync2("python", ["-c", script, filePath], {
    timeout: 3e4,
    maxBuffer: 50 * 1024 * 1024
  });
  return { content: stdout, convertedBy: "markitdown" };
}
function parseMarkdownToText(md) {
  let text = md;
  text = text.replace(/^---[\s\S]*?---\n?/, "");
  text = text.replace(/^(#{1,6})\s+(.+)$/gm, (_, hashes, title) => {
    return `${"#".repeat(hashes.length)} ${title}`;
  });
  text = text.replace(/```[\w]*\n([\s\S]*?)```/g, (_, code) => code.trim());
  text = text.replace(/`([^`]+)`/g, "$1");
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, "$1");
  text = text.replace(/\*\*(.+?)\*\*/g, "$1");
  text = text.replace(/\*(.+?)\*/g, "$1");
  text = text.replace(/___(.+?)___/g, "$1");
  text = text.replace(/__(.+?)__/g, "$1");
  text = text.replace(/_(.+?)_/g, "$1");
  text = text.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");
  text = text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  text = text.replace(/^[\s]*[-*+]\s+/gm, "- ");
  text = text.replace(/^[\s]*\d+\.\s+/gm, (match) => match);
  text = text.replace(/^>\s?/gm, "");
  text = text.replace(/^[-*_]{3,}\s*$/gm, "---");
  text = text.replace(/<[^>]+>/g, "");
  text = text.replace(/\n{3,}/g, "\n\n");
  return text.trim();
}
function parseMarkdownToStructured(md) {
  return {
    headings: extractHeadings(md),
    codeBlocks: extractCodeBlocks(md),
    links: extractLinks(md),
    tables: extractTables(md),
    plainText: parseMarkdownToText(md),
    frontmatter: extractFrontmatter(md)
  };
}
function extractFrontmatter(md) {
  const match = md.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return null;
  const result = {};
  for (const line of match[1].split("\n")) {
    const colonIdx = line.indexOf(":");
    if (colonIdx > 0) {
      const key = line.substring(0, colonIdx).trim();
      const value = line.substring(colonIdx + 1).trim();
      result[key] = value;
    }
  }
  return result;
}
function extractHeadings(md) {
  const headings = [];
  const regex = /^(#{1,6})\s+(.+)$/gm;
  let match;
  while ((match = regex.exec(md)) !== null) {
    headings.push({ level: match[1].length, text: match[2].trim() });
  }
  return headings;
}
function extractCodeBlocks(md) {
  const blocks = [];
  const regex = /```(\w*)\n([\s\S]*?)```/g;
  let match;
  while ((match = regex.exec(md)) !== null) {
    blocks.push({ lang: match[1] || "text", code: match[2].trim() });
  }
  return blocks;
}
function extractLinks(md) {
  const links = [];
  const regex = /\[([^\]]+)\]\(([^)]+)\)/g;
  let match;
  while ((match = regex.exec(md)) !== null) {
    links.push({ text: match[1], url: match[2] });
  }
  return links;
}
function extractTables(md) {
  const tables = [];
  const tableRegex = /\|(.+)\|\n\|[-| ]+\|\n((?:\|.+\|\n?)+)/g;
  let match;
  while ((match = tableRegex.exec(md)) !== null) {
    const headers = match[1].split("|").map((h) => h.trim()).filter(Boolean);
    const rows = match[2].trim().split("\n").map(
      (row) => row.split("|").map((cell) => cell.trim()).filter(Boolean)
    );
    tables.push({ headers, rows });
  }
  return tables;
}
class FileReaderNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "file-reader";
  }
  getMetadata() {
    return {
      type: "file-reader",
      label: "File Reader",
      icon: "file-text",
      category: "tools",
      description: "Read file content. Auto-detect format. markitdown for office/pdf/images.",
      inputs: [
        { name: "path", label: "File Path", type: "string", required: true }
      ],
      outputs: [
        { name: "content", label: "Content", type: "string", required: false },
        { name: "metadata", label: "Metadata", type: "object", required: false }
      ],
      defaultConfig: { mode: "auto", max_size_mb: 10 }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const filePath = String(inputs.path || cfg.path || "");
    const mode = cfg.mode || "auto";
    const maxSizeMb = cfg.max_size_mb || 10;
    if (!filePath) {
      throw new NodeExecutionError(context.nodeId, this.type, "File path is required");
    }
    const fs = await import("fs/promises");
    let stat;
    try {
      stat = await fs.stat(filePath);
    } catch {
      throw new NodeExecutionError(context.nodeId, this.type, `File not found: ${filePath}`);
    }
    if (stat.size > maxSizeMb * 1024 * 1024) {
      throw new NodeExecutionError(context.nodeId, this.type, `File too large: ${(stat.size / 1024 / 1024).toFixed(1)}MB (max: ${maxSizeMb}MB)`);
    }
    const info = detectFileType(filePath);
    const fileName = getFileName(filePath);
    const ext = getExtension(filePath);
    const language = getLanguage(filePath);
    let content;
    let convertedBy;
    if (mode === "plain") {
      const result = await readAsPlainText(filePath);
      content = result;
      convertedBy = "plain_text";
    } else if (mode === "markdown") {
      const result = await convertFile(filePath, { useMarkitdown: true });
      content = result.content;
      convertedBy = result.convertedBy;
    } else if (mode === "structured") {
      const raw = await readAsPlainText(filePath);
      const structured = parseMarkdownToStructured(raw);
      content = JSON.stringify(structured, null, 2);
      convertedBy = "structured";
    } else {
      if (info.parser === "skip") {
        content = `[Binary file: ${fileName}]`;
        convertedBy = "binary_skip";
      } else if (info.parser === "markitdown") {
        const result = await convertFile(filePath);
        content = result.content;
        convertedBy = result.convertedBy;
      } else if (info.parser === "markdown") {
        const raw = await readAsPlainText(filePath);
        content = parseMarkdownToText(raw);
        convertedBy = "markdown_parser";
      } else {
        const result = await readAsPlainText(filePath);
        content = result;
        convertedBy = "plain_text";
      }
    }
    const lineCount = content.split("\n").length;
    return {
      content,
      metadata: {
        path: filePath,
        name: fileName,
        extension: ext,
        size: stat.size,
        format: info.category,
        language,
        line_count: lineCount,
        char_count: content.length,
        converted_by: convertedBy
      }
    };
  }
}
async function readAsPlainText(filePath) {
  const fs = await import("fs/promises");
  return fs.readFile(filePath, "utf-8");
}
const DEFAULT_EXCLUDE$1 = ["node_modules", ".git", "dist", "out", ".next", "__pycache__", ".venv", "venv", ".cache", "coverage"];
function buildTree(dirPath, readdir, isDir, options = {}) {
  const {
    excludePatterns = DEFAULT_EXCLUDE$1,
    maxDepth = 10,
    maxEntries = 1e3,
    includeHidden = false,
    showFiles = true
  } = options;
  let entryCount = 0;
  function build(currentPath, depth) {
    if (depth > maxDepth) return null;
    if (entryCount >= maxEntries) return null;
    const name = getFileName(currentPath) || currentPath;
    const isDirectory = isDir(currentPath);
    if (!isDirectory) {
      if (!showFiles) return null;
      if (shouldSkipFile(currentPath)) return null;
      entryCount++;
      return { name, path: currentPath, isDirectory: false };
    }
    if (shouldExclude(name, excludePatterns, includeHidden)) return null;
    let entries;
    try {
      entries = readdir(currentPath);
    } catch {
      return null;
    }
    const children = [];
    for (const entry of entries) {
      if (entryCount >= maxEntries) break;
      const childPath = `${currentPath}/${entry}`;
      const child = build(childPath, depth + 1);
      if (child) children.push(child);
    }
    children.sort((a, b) => {
      if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    entryCount++;
    return { name, path: currentPath, isDirectory: true, children };
  }
  return build(dirPath, 0);
}
function shouldExclude(name, patterns, includeHidden) {
  if (!includeHidden && name.startsWith(".")) return true;
  return patterns.includes(name);
}
function renderTree(node, prefix = "", isLast = true) {
  const lines = [];
  const connector = isLast ? "└── " : "├── ";
  const childPrefix = prefix + (isLast ? "    " : "│   ");
  if (node.isDirectory) {
    lines.push(`${prefix}${connector}${node.name}/`);
    if (node.children) {
      node.children.forEach((child, i) => {
        const last = i === node.children.length - 1;
        lines.push(renderTree(child, childPrefix, last));
      });
    }
  } else {
    lines.push(`${prefix}${connector}${node.name}`);
  }
  return lines.join("\n");
}
function treeToString(root) {
  const lines = [`${root.name}/`];
  if (root.children) {
    root.children.forEach((child, i) => {
      const last = i === root.children.length - 1;
      lines.push(renderTree(child, "", last));
    });
  }
  return lines.join("\n");
}
const DEFAULT_EXCLUDE = ["node_modules", ".git", "dist", "out", ".next", "__pycache__", ".venv", "venv", ".cache", "coverage"];
const DEFAULT_FILE_TYPES = ["ts", "tsx", "js", "jsx", "py", "java", "go", "rs", "c", "cpp", "h", "cs", "rb", "php", "swift", "kt", "json", "yaml", "yml", "toml", "md", "mdx", "txt", "html", "css", "scss", "sql", "sh", "dockerfile"];
class ContextLoaderNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "context-loader";
  }
  getMetadata() {
    return {
      type: "context-loader",
      label: "Context Loader",
      icon: "database",
      category: "tools",
      description: "Load directory tree as structured context for LLM. Tree + file content.",
      inputs: [
        { name: "root_path", label: "Root Path", type: "string", required: true }
      ],
      outputs: [
        { name: "context", label: "Context", type: "string", required: false },
        { name: "tree", label: "Tree", type: "string", required: false },
        { name: "files_loaded", label: "Files Loaded", type: "number", required: false },
        { name: "files_skipped", label: "Files Skipped", type: "number", required: false }
      ],
      defaultConfig: {
        file_types: DEFAULT_FILE_TYPES,
        exclude_patterns: DEFAULT_EXCLUDE,
        max_files: 50,
        max_total_chars: 1e5,
        include_tree: true,
        include_file_content: true,
        tree_only: false,
        convert_office_docs: false,
        convert_pdfs: false
      }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const rootPath = String(inputs.root_path || cfg.root_path || "");
    if (!rootPath) {
      throw new NodeExecutionError(context.nodeId, this.type, "Root path is required");
    }
    const fs = await import("fs/promises");
    const path2 = await import("path");
    const excludePatterns = cfg.exclude_patterns || DEFAULT_EXCLUDE;
    const maxFiles = cfg.max_files || 50;
    const maxTotalChars = cfg.max_total_chars || 1e5;
    const includeTree = cfg.include_tree !== false;
    const includeContent = cfg.include_file_content !== false;
    const treeOnly = cfg.tree_only || false;
    const fileTypes = (cfg.file_types || DEFAULT_FILE_TYPES).map((t) => t.startsWith(".") ? t.substring(1).toLowerCase() : t.toLowerCase());
    let treeStr = "";
    if (includeTree || treeOnly) {
      const { readdirSync, statSync } = await import("fs");
      const tree = buildTree(
        rootPath,
        (p) => {
          try {
            return readdirSync(p);
          } catch {
            return [];
          }
        },
        (p) => {
          try {
            return statSync(p).isDirectory();
          } catch {
            return false;
          }
        },
        { excludePatterns, maxDepth: 8, maxEntries: 500, showFiles: !treeOnly }
      );
      if (tree) treeStr = treeToString(tree);
    }
    if (treeOnly) {
      return { context: treeStr, tree: treeStr, files_loaded: 0, files_skipped: 0 };
    }
    const files = [];
    let skipped = 0;
    async function scan(dirPath, depth) {
      if (depth > 8 || files.length >= maxFiles) return;
      let entries;
      try {
        entries = await fs.readdir(dirPath);
      } catch {
        return;
      }
      for (const entry of entries) {
        if (files.length >= maxFiles) break;
        if (entry.startsWith(".")) continue;
        if (excludePatterns.includes(entry)) continue;
        const fullPath = path2.join(dirPath, entry);
        let stat;
        try {
          stat = await fs.stat(fullPath);
        } catch {
          continue;
        }
        if (stat.isDirectory()) {
          await scan(fullPath, depth + 1);
        } else {
          const ext = getExtension(entry);
          if (fileTypes.length > 0 && !fileTypes.includes(ext)) {
            skipped++;
            continue;
          }
          const info = detectFileType(entry);
          if (info.isBinary || info.parser === "skip") {
            skipped++;
            continue;
          }
          try {
            let content;
            if (info.parser === "markitdown" && (cfg.convert_office_docs || cfg.convert_pdfs)) {
              const result = await convertFile(fullPath);
              content = result.content;
            } else if (info.parser === "markdown") {
              const raw = await fs.readFile(fullPath, "utf-8");
              content = parseMarkdownToText(raw);
            } else {
              content = await fs.readFile(fullPath, "utf-8");
            }
            files.push({
              path: fullPath,
              relativePath: path2.relative(rootPath, fullPath),
              content,
              language: info.language,
              size: stat.size
            });
          } catch {
            skipped++;
          }
        }
      }
    }
    await scan(rootPath, 0);
    const parts = [];
    if (includeTree && treeStr) {
      parts.push("## Project Structure\n```\n" + treeStr + "\n```\n");
    }
    if (includeContent) {
      let totalChars = parts.join("").length;
      for (const file of files) {
        const header = `## File: ${file.relativePath}`;
        const block = file.language ? `${header}
\`\`\`${file.language}
${file.content}
\`\`\`
` : `${header}
${file.content}
`;
        if (totalChars + block.length > maxTotalChars) break;
        parts.push(block);
        totalChars += block.length;
      }
    }
    return {
      context: parts.join("\n"),
      tree: treeStr,
      files_loaded: files.length,
      files_skipped: skipped
    };
  }
}
const FINISH_PATTERNS = [
  /FINISH[:\s]*(.*)/is,
  /FINAL[_\s]ANSWER[:\s]*(.*)/is,
  /I['']m\s+done[.\s]*(.*)/is,
  /Task\s+complete[d]?[.\s]*(.*)/is
];
const TOOL_JSON_PATTERN = /```json\s*\n([\s\S]*?)\n```/;
function parseAgentOutput(output) {
  const thought = extractThought(output);
  for (const pattern of FINISH_PATTERNS) {
    const match = output.match(pattern);
    if (match) {
      return {
        type: "finish",
        thought,
        finalAnswer: match[1]?.trim() || thought
      };
    }
  }
  const toolCall = extractToolCall(output);
  if (toolCall) {
    return {
      type: "tool_call",
      thought,
      toolName: toolCall.name,
      toolArgs: toolCall.args
    };
  }
  return {
    type: "unknown",
    thought
  };
}
function extractThought(output) {
  const thoughtMatch = output.match(/Thought[:\s]*(.*?)(?=\s*(?:Action|Tool|FINISH|$))/is);
  if (thoughtMatch) return thoughtMatch[1].trim();
  const lines = output.split("\n").filter((l) => l.trim());
  if (lines.length > 0) return lines[0].trim();
  return output.substring(0, 200);
}
function extractToolCall(output) {
  const jsonMatch = output.match(TOOL_JSON_PATTERN);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[1]);
      if (parsed.tool || parsed.name || parsed.function) {
        const name = parsed.tool || parsed.name || parsed.function;
        const args = parsed.args || parsed.arguments || parsed.parameters || parsed.input || {};
        return { name, args: typeof args === "string" ? JSON.parse(args) : args };
      }
    } catch {
    }
  }
  const actionMatch = output.match(/(?:Action|Tool)[:\s]*["']?(\w+)["']?\s*(?:Arguments?|Input|Args)[:\s]*(\{[\s\S]*?\})/is);
  if (actionMatch) {
    try {
      return { name: actionMatch[1], args: JSON.parse(actionMatch[2]) };
    } catch {
    }
  }
  const simpleMatch = output.match(/(?:use|call|invoke|execute)\s+(?:tool\s+)?["']?(\w+)["']?\s*(?:with|:)\s*(\{[\s\S]*?\})/is);
  if (simpleMatch) {
    try {
      return { name: simpleMatch[1], args: JSON.parse(simpleMatch[2]) };
    } catch {
    }
  }
  return null;
}
function buildToolResultPrompt(toolName, result) {
  return `Observation: Tool '${toolName}' returned:
${result}

Thought:`;
}
function buildAgentSystemPrompt(tools) {
  const toolDescriptions = tools.map((t) => {
    const params = t.parameters.map((p) => {
      const p2 = p;
      return `  - ${p2.name} (${p2.type}${p2.required ? ", required" : ""}): ${p2.description}`;
    }).join("\n");
    return `### ${t.name}
${t.description}
Parameters:
${params}`;
  }).join("\n\n");
  return `You are a helpful AI assistant that can use tools to complete tasks.

Available Tools:
${toolDescriptions}

To use a tool, respond with:
Thought: <your reasoning about what to do next>
Action:
\`\`\`json
{"tool": "<tool_name>", "args": {"<param>": "<value>"}}
\`\`\`

When you have completed the task, respond with:
Thought: <summary of what you accomplished>
FINISH: <your final answer>

Important:
- Always start with a Thought
- Use tools when needed, don't make up information
- If a tool returns an error, try a different approach
- When the task is complete, use FINISH`;
}
const toolRegistry = /* @__PURE__ */ new Map();
function registerTool(tool) {
  toolRegistry.set(tool.name, tool);
}
function getTool(name) {
  return toolRegistry.get(name);
}
function checkPermission(tool, permission) {
  if (permission.blockedTools?.includes(tool.name)) {
    throw new Error(`Tool '${tool.name}' is blocked by permission policy`);
  }
  if (permission.allowedTools && !permission.allowedTools.includes(tool.name)) {
    throw new Error(`Tool '${tool.name}' is not in allowed tools list`);
  }
}
async function runCode(args, ctx) {
  const language = String(args.language || "python");
  const code = String(args.code || "");
  if (!code) return "Error: No code provided";
  try {
    const sandbox = await createSandbox({ workflowId: ctx.nodeId, runId: `agent-${ctx.nodeId}` });
    const result = await sandbox.execCode(language, code);
    if (result.stderr && !result.stdout) return `Error: ${result.stderr}`;
    return result.stdout || "(no output)";
  } catch (error) {
    return `Error: ${error instanceof Error ? error.message : "Code execution failed"}`;
  }
}
async function runCommand(args, ctx) {
  const command = String(args.command || "");
  if (!command) return "Error: No command provided";
  try {
    const sandbox = await createSandbox({ workflowId: ctx.nodeId, runId: `agent-${ctx.nodeId}` });
    const result = await sandbox.exec(command, { timeoutMs: 3e4 });
    if (result.exitCode !== 0 && !result.stdout) return `Error (exit ${result.exitCode}): ${result.stderr}`;
    return result.stdout || result.stderr || "(no output)";
  } catch (error) {
    return `Error: ${error instanceof Error ? error.message : "Command failed"}`;
  }
}
async function readFile(args, ctx) {
  const filePath = String(args.path || "");
  if (!filePath) return "Error: No file path provided";
  try {
    const sandbox = await createSandbox({ workflowId: ctx.nodeId, runId: `agent-${ctx.nodeId}` });
    const content = await sandbox.readFile(filePath);
    if (content.length > 5e4) return content.substring(0, 5e4) + "\n... [truncated]";
    return content;
  } catch (error) {
    return `Error reading file: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}
async function writeFile(args, ctx) {
  const filePath = String(args.path || "");
  const content = String(args.content || "");
  if (!filePath) return "Error: No file path provided";
  try {
    const sandbox = await createSandbox({ workflowId: ctx.nodeId, runId: `agent-${ctx.nodeId}` });
    await sandbox.writeFile(filePath, content);
    return `Successfully wrote ${content.length} characters to ${filePath}`;
  } catch (error) {
    return `Error writing file: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}
async function searchMemory(args, _ctx) {
  const query = String(args.query || "");
  if (!query) return "Error: No query provided";
  return "Memory search not available yet. Will be implemented in F6 integration.";
}
async function httpRequest(args, _ctx) {
  const url = String(args.url || "");
  const method = String(args.method || "GET").toUpperCase();
  const body = args.body;
  if (!url) return "Error: No URL provided";
  try {
    const response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : void 0
    });
    const text = await response.text();
    if (text.length > 1e4) return text.substring(0, 1e4) + "\n... [truncated]";
    return text;
  } catch (error) {
    return `Error: ${error instanceof Error ? error.message : "Request failed"}`;
  }
}
const builtinTools = [
  {
    name: "run_code",
    description: "Execute Python or JavaScript code in a sandbox. Use for calculations, data processing, or testing logic.",
    parameters: [
      { name: "language", type: "string", description: "Programming language: python or javascript", required: true },
      { name: "code", type: "string", description: "Code to execute", required: true }
    ],
    handler: "sandbox_code",
    handlerFn: runCode
  },
  {
    name: "run_command",
    description: "Execute a shell command. Use for running scripts, installing packages, or system operations.",
    parameters: [
      { name: "command", type: "string", description: "Shell command to execute", required: true }
    ],
    handler: "sandbox_shell",
    handlerFn: runCommand
  },
  {
    name: "read_file",
    description: "Read the contents of a file from the filesystem.",
    parameters: [
      { name: "path", type: "string", description: "Absolute path to the file", required: true }
    ],
    handler: "file_read",
    handlerFn: readFile
  },
  {
    name: "write_file",
    description: "Write content to a file. Creates parent directories if needed.",
    parameters: [
      { name: "path", type: "string", description: "Absolute path to the file", required: true },
      { name: "content", type: "string", description: "Content to write", required: true }
    ],
    handler: "file_write",
    handlerFn: writeFile
  },
  {
    name: "search_memory",
    description: "Search workflow memory for relevant context from past executions.",
    parameters: [
      { name: "query", type: "string", description: "Search query", required: true },
      { name: "type", type: "string", description: "Memory type: semantic, episodic, or procedural", required: false }
    ],
    handler: "memory_search",
    handlerFn: searchMemory
  },
  {
    name: "http_request",
    description: "Make an HTTP request to an external API endpoint.",
    parameters: [
      { name: "url", type: "string", description: "URL to request", required: true },
      { name: "method", type: "string", description: "HTTP method: GET, POST, PUT, DELETE", required: false },
      { name: "body", type: "object", description: "Request body for POST/PUT", required: false }
    ],
    handler: "http",
    handlerFn: httpRequest
  }
];
function registerBuiltinTools() {
  for (const tool of builtinTools) {
    registerTool(tool);
  }
}
let toolsRegistered$1 = false;
class ReActAgentNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "react-agent";
  }
  getMetadata() {
    return {
      type: "react-agent",
      label: "ReAct Agent",
      icon: "robot",
      category: "agent",
      description: "Thought → Action → Observation loop. Multi-step reasoning with tools.",
      inputs: [
        { name: "task", label: "Task", type: "string", required: true },
        { name: "context", label: "Context", type: "string", required: false }
      ],
      outputs: [
        { name: "output", label: "Output", type: "string", required: false },
        { name: "iterations", label: "Iterations", type: "number", required: false },
        { name: "thoughts", label: "Thoughts", type: "array", required: false }
      ],
      defaultConfig: {
        model: "gpt-4o",
        provider: "openai",
        max_iterations: 25,
        max_time_seconds: 300,
        tools: ["run_code", "read_file", "write_file", "search_memory"],
        use_memory: false
      }
    };
  }
  async run(inputs, config, pool, context) {
    if (!toolsRegistered$1) {
      registerBuiltinTools();
      toolsRegistered$1 = true;
    }
    const cfg = config;
    const task = String(inputs.task || "");
    const contextStr = inputs.context ? String(inputs.context) : "";
    const maxIterations = cfg.max_iterations || 25;
    const maxTimeMs = (cfg.max_time_seconds || 300) * 1e3;
    const model = cfg.model || "gpt-4o";
    const provider = cfg.provider || "openai";
    const permission = cfg.permissions || {};
    if (!task) {
      throw new NodeExecutionError(context.nodeId, this.type, "Task is required");
    }
    const allowedToolNames = cfg.tools || ["run_code", "read_file", "write_file"];
    const tools = allowedToolNames.map((name) => getTool(name)).filter((t) => t !== void 0);
    for (const tool of tools) {
      checkPermission(tool, permission);
    }
    const systemPrompt = cfg.system_prompt || buildAgentSystemPrompt(tools);
    const messages = [
      { role: "system", content: systemPrompt }
    ];
    if (contextStr) {
      messages.push({ role: "system", content: `Context:
${contextStr}` });
    }
    messages.push({ role: "user", content: task });
    const thoughts = [];
    const startTime = Date.now();
    let finalAnswer = "";
    const toolContext = {
      pool,
      nodeId: context.nodeId,
      signal: context.signal
    };
    for (let i = 0; i < maxIterations; i++) {
      if (context.signal?.aborted) {
        throw new AgentError("Agent aborted by user");
      }
      if (Date.now() - startTime > maxTimeMs) {
        throw new AgentError(`Agent timeout: exceeded ${maxTimeMs}ms`);
      }
      let llmOutput;
      try {
        llmOutput = await window.api.ai.chat(messages, { model, provider });
      } catch (error) {
        const message = error instanceof Error ? error.message : "LLM call failed";
        throw new AgentError(`Agent LLM error at iteration ${i}: ${message}`, { cause: error });
      }
      const parsed = parseAgentOutput(llmOutput);
      thoughts.push(parsed.thought);
      if (parsed.type === "finish") {
        finalAnswer = parsed.finalAnswer || parsed.thought;
        break;
      }
      if (parsed.type === "tool_call" && parsed.toolName) {
        messages.push({ role: "assistant", content: llmOutput });
        const tool = getTool(parsed.toolName);
        if (!tool) {
          messages.push({ role: "user", content: `Error: Tool '${parsed.toolName}' not found. Available tools: ${allowedToolNames.join(", ")}` });
          continue;
        }
        if (!allowedToolNames.includes(tool.name)) {
          messages.push({ role: "user", content: `Error: Tool '${tool.name}' is not enabled for this agent.` });
          continue;
        }
        let toolResult;
        try {
          if (tool.handlerFn) {
            toolResult = await tool.handlerFn(parsed.toolArgs || {}, toolContext);
          } else {
            toolResult = await this.executeHandler(tool, parsed.toolArgs || {}, toolContext);
          }
        } catch (error) {
          toolResult = `Error: ${error instanceof Error ? error.message : "Tool execution failed"}`;
        }
        messages.push({ role: "user", content: buildToolResultPrompt(parsed.toolName, toolResult) });
        continue;
      }
      messages.push({ role: "assistant", content: llmOutput });
      messages.push({ role: "user", content: "Please use a tool or provide a FINISH response." });
    }
    if (!finalAnswer && thoughts.length > 0) {
      finalAnswer = thoughts[thoughts.length - 1];
    }
    return {
      output: finalAnswer,
      iterations: thoughts.length,
      thoughts
    };
  }
  async executeHandler(tool, args, context) {
    switch (tool.handler) {
      case "file_read": {
        const filePath = String(args.path || "");
        const fs = await import("fs/promises");
        return fs.readFile(filePath, "utf-8");
      }
      case "file_write": {
        const filePath = String(args.path || "");
        const content = String(args.content || "");
        const fs = await import("fs/promises");
        const { dirname } = await import("path");
        await fs.mkdir(dirname(filePath), { recursive: true });
        await fs.writeFile(filePath, content, "utf-8");
        return `Written ${content.length} chars to ${filePath}`;
      }
      case "http": {
        const url = String(args.url || "");
        const method = String(args.method || "GET");
        const response = await fetch(url, { method, headers: { "Content-Type": "application/json" } });
        return response.text();
      }
      default:
        return `Handler '${tool.handler}' not implemented yet.`;
    }
  }
}
function buildAgentSystemPromptFromDef(agent, tools) {
  const toolDescs = tools.map((t) => `- ${t.name}: ${t.description}`).join("\n");
  return `You are ${agent.name}, a ${agent.role}.

Background: ${agent.backstory}

Your goal: ${agent.goal}

${agent.systemPrompt ? `Additional instructions: ${agent.systemPrompt}
` : ""}
Available tools:
${toolDescs}

${agent.allowDelegation ? "You CAN delegate tasks to other agents using delegate_work or ask_question." : "You CANNOT delegate tasks. Complete the work yourself."}

Respond with:
Thought: <your reasoning>
Action:
\`\`\`json
{"tool": "<tool_name>", "args": {<params>}}
\`\`\`

When done:
Thought: <summary>
FINISH: <your result>`;
}
function createAgent(overrides) {
  return {
    goal: "",
    backstory: "",
    model: "gpt-4o",
    provider: "openai",
    tools: ["read_file", "write_file"],
    allowDelegation: false,
    maxIterations: 10,
    ...overrides
  };
}
function createTeamState(task, expectedOutput) {
  return {
    task,
    plan: "",
    facts: [],
    agentOutputs: {},
    taskResults: [],
    messages: [],
    currentRound: 0,
    stallCount: 0,
    status: "planning",
    expectedOutput
  };
}
function addMessage(state, msg) {
  state.messages.push({ ...msg, timestamp: Date.now() });
}
function setAgentOutput(state, agentId, output) {
  state.agentOutputs[agentId] = output;
}
function addTaskResult(state, result) {
  state.taskResults.push(result);
}
function getAgentContext(state, agentId) {
  const parts = [];
  if (state.plan) parts.push(`Plan:
${state.plan}`);
  if (state.facts.length > 0) parts.push(`Facts:
${state.facts.map((f) => `- ${f}`).join("\n")}`);
  const otherOutputs = Object.entries(state.agentOutputs).filter(([id]) => id !== agentId);
  if (otherOutputs.length > 0) {
    parts.push(`Other agent outputs:
${otherOutputs.map(([id, out]) => `[${id}]: ${out.substring(0, 500)}`).join("\n")}`);
  }
  const recentMessages = state.messages.filter((m) => m.to === agentId || m.from === agentId).slice(-5);
  if (recentMessages.length > 0) {
    parts.push(`Recent messages:
${recentMessages.map((m) => `[${m.from}→${m.to}] ${m.content.substring(0, 200)}`).join("\n")}`);
  }
  return parts.join("\n\n");
}
async function runSequential(agents, state, signal) {
  const results = [];
  let previousOutput = "";
  for (const agent of agents) {
    if (signal?.aborted) throw new AgentError("Aborted");
    const tools = agent.tools.map((name) => getTool(name)).filter((t) => t !== void 0);
    const systemPrompt = buildAgentSystemPromptFromDef(agent, tools);
    let context = state.task;
    if (previousOutput) {
      context = `Previous agent output:
${previousOutput}

Your task: ${state.task}`;
    }
    const messages = [
      { role: "system", content: systemPrompt },
      { role: "user", content: context }
    ];
    addMessage(state, { from: "orchestrator", to: agent.id, type: "task", content: context });
    let finalOutput = "";
    let iterations = 0;
    for (let i = 0; i < agent.maxIterations; i++) {
      if (signal?.aborted) throw new AgentError("Aborted");
      iterations++;
      let llmOutput;
      try {
        llmOutput = await window.api.ai.chat(messages, { model: agent.model, provider: agent.provider });
      } catch (error) {
        const msg = error instanceof Error ? error.message : "LLM failed";
        const result2 = { agentId: agent.id, output: `Error: ${msg}`, success: false, iterations };
        addTaskResult(state, result2);
        results.push(result2);
        break;
      }
      const parsed = parseAgentOutput(llmOutput);
      if (parsed.type === "finish") {
        finalOutput = parsed.finalAnswer || parsed.thought;
        break;
      }
      if (parsed.type === "tool_call" && parsed.toolName) {
        messages.push({ role: "assistant", content: llmOutput });
        const tool = getTool(parsed.toolName);
        let toolResult = `Tool '${parsed.toolName}' not found`;
        if (tool?.handlerFn) {
          try {
            toolResult = await tool.handlerFn(parsed.toolArgs || {}, { pool: void 0, nodeId: agent.id, signal });
          } catch (e) {
            toolResult = `Error: ${e instanceof Error ? e.message : "Tool failed"}`;
          }
        }
        messages.push({ role: "user", content: buildToolResultPrompt(parsed.toolName, toolResult) });
        continue;
      }
      messages.push({ role: "assistant", content: llmOutput });
      messages.push({ role: "user", content: "Please use a tool or FINISH." });
    }
    if (!finalOutput) finalOutput = "Agent did not produce a final answer.";
    const result = { agentId: agent.id, output: finalOutput, success: true, iterations };
    addTaskResult(state, result);
    setAgentOutput(state, agent.id, finalOutput);
    addMessage(state, { from: agent.id, to: "orchestrator", type: "result", content: finalOutput });
    results.push(result);
    previousOutput = finalOutput;
  }
  return {
    success: results.every((r) => r.success),
    output: previousOutput,
    results
  };
}
function buildLedgerPrompt(state, agentIds) {
  const recentResults = state.taskResults.slice(-5).map(
    (r) => `- ${r.agentId}: ${r.success ? "success" : "failed"} — ${r.output.substring(0, 300)}`
  ).join("\n");
  return `You are a task orchestrator managing a team of agents.

TASK: ${state.task}
EXPECTED OUTPUT: ${state.expectedOutput}
CURRENT ROUND: ${state.currentRound}

PLAN:
${state.plan || "No plan yet"}

FACTS:
${state.facts.map((f) => `- ${f}`).join("\n") || "None"}

RECENT RESULTS:
${recentResults || "None"}

AVAILABLE AGENTS: ${agentIds.join(", ")}

Evaluate progress and respond in this EXACT JSON format:
{
  "is_request_satisfied": {"answer": true/false, "reason": "..."},
  "is_progress_being_made": {"answer": true/false, "reason": "..."},
  "is_in_loop": {"answer": true/false, "reason": "..."},
  "next_speaker": {"answer": "<agent_id>", "reason": "..."},
  "instruction_or_question": {"answer": "<what to tell the next agent>"}
}

Only respond with the JSON object.`;
}
function parseLedgerResponse(response) {
  try {
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (!jsonMatch) return null;
    const parsed = JSON.parse(jsonMatch[0]);
    return {
      isRequestSatisfied: {
        answer: Boolean(parsed.is_request_satisfied?.answer),
        reason: String(parsed.is_request_satisfied?.reason || "")
      },
      isProgressBeingMade: {
        answer: Boolean(parsed.is_progress_being_made?.answer ?? true),
        reason: String(parsed.is_progress_being_made?.reason || "")
      },
      isInLoop: {
        answer: Boolean(parsed.is_in_loop?.answer),
        reason: String(parsed.is_in_loop?.reason || "")
      },
      nextSpeaker: {
        answer: String(parsed.next_speaker?.answer || ""),
        reason: String(parsed.next_speaker?.reason || "")
      },
      instructionOrQuestion: {
        answer: String(parsed.instruction_or_question?.answer || "")
      }
    };
  } catch {
    return null;
  }
}
function detectStall(ledger, currentStallCount) {
  if (!ledger.isProgressBeingMade.answer || ledger.isInLoop.answer) {
    return currentStallCount + 1;
  }
  return 0;
}
function shouldReplan(stallCount, maxStalls) {
  return stallCount >= maxStalls;
}
function buildPlanningPrompt(task, agents) {
  const agentDescs = agents.map(
    (a) => `- ${a.id} (${a.role}): ${a.goal}. Tools: ${a.tools.join(", ")}`
  ).join("\n");
  return `You are planning how to complete this task using a team of agents.

TASK: ${task}

AVAILABLE AGENTS:
${agentDescs}

Create a plan with:
1. Key facts/assumptions
2. Execution steps (ordered)
3. Agent assignment for each step

Respond in this EXACT JSON format:
{
  "facts": ["fact 1", "fact 2"],
  "steps": ["step 1: description", "step 2: description"],
  "agent_assignments": [
    {"agent_id": "<id>", "task": "<specific task description>"},
    {"agent_id": "<id>", "task": "<specific task description>"}
  ]
}

Only respond with the JSON object.`;
}
function buildReplanPrompt(state, agents) {
  const failedResults = state.taskResults.filter((r) => !r.success).map(
    (r) => `- ${r.agentId}: ${r.output.substring(0, 300)}`
  ).join("\n");
  const completedResults = state.taskResults.filter((r) => r.success).map(
    (r) => `- ${r.agentId}: ${r.output.substring(0, 300)}`
  ).join("\n");
  return `The current plan is not working. Re-analyze and create a new plan.

TASK: ${state.task}
EXPECTED OUTPUT: ${state.expectedOutput}

CURRENT PLAN:
${state.plan}

COMPLETED:
${completedResults || "None"}

FAILED/STALLED:
${failedResults || "None"}

FACTS:
${state.facts.map((f) => `- ${f}`).join("\n")}

AVAILABLE AGENTS: ${agents.map((a) => `${a.id} (${a.role})`).join(", ")}

Create an UPDATED plan. Respond in JSON:
{
  "facts": ["updated facts"],
  "steps": ["new step 1", "new step 2"],
  "agent_assignments": [{"agent_id": "<id>", "task": "<task>"}]
}`;
}
function parsePlanResponse(response) {
  try {
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (!jsonMatch) return null;
    const parsed = JSON.parse(jsonMatch[0]);
    return {
      facts: Array.isArray(parsed.facts) ? parsed.facts.map(String) : [],
      steps: Array.isArray(parsed.steps) ? parsed.steps.map(String) : [],
      agentAssignments: Array.isArray(parsed.agent_assignments) ? parsed.agent_assignments.map((a) => ({
        agentId: String(a.agent_id || ""),
        task: String(a.task || "")
      })) : []
    };
  } catch {
    return null;
  }
}
function buildTaskPromptForAgent(agent, assignment, state) {
  const parts = [assignment];
  if (state.facts.length > 0) {
    parts.push(`
Known facts:
${state.facts.map((f) => `- ${f}`).join("\n")}`);
  }
  const otherOutputs = Object.entries(state.agentOutputs).filter(([id]) => id !== agent.id);
  if (otherOutputs.length > 0) {
    parts.push(`
Results from other agents:
${otherOutputs.map(([id, out]) => `[${id}]: ${out.substring(0, 1e3)}`).join("\n")}`);
  }
  return parts.join("\n");
}
async function runHierarchical(agents, state, config, signal) {
  const agentMap = new Map(agents.map((a) => [a.id, a]));
  const agentIds = agents.map((a) => a.id);
  const results = [];
  if (config.planning) {
    state.status = "planning";
    const planPrompt = buildPlanningPrompt(state.task, agents);
    try {
      const planResponse = await window.api.ai.chat(
        [{ role: "user", content: planPrompt }],
        { model: config.managerModel, provider: config.managerProvider }
      );
      const plan = parsePlanResponse(planResponse);
      if (plan) {
        state.plan = plan.steps.join("\n");
        state.facts = plan.facts;
      }
    } catch {
    }
  }
  state.status = "executing";
  for (let round = 0; round < config.maxRounds; round++) {
    if (signal?.aborted) throw new AgentError("Aborted");
    state.currentRound = round;
    const ledgerPrompt = buildLedgerPrompt(state, agentIds);
    let ledger = null;
    try {
      const ledgerResponse = await window.api.ai.chat(
        [{ role: "user", content: ledgerPrompt }],
        { model: config.managerModel, provider: config.managerProvider }
      );
      ledger = parseLedgerResponse(ledgerResponse);
    } catch {
    }
    if (!ledger) {
      ledger = {
        isRequestSatisfied: { answer: false, reason: "Ledger eval failed" },
        isProgressBeingMade: { answer: true, reason: "Continuing" },
        isInLoop: { answer: false, reason: "" },
        nextSpeaker: { answer: agentIds[round % agentIds.length], reason: "Round-robin" },
        instructionOrQuestion: { answer: state.task }
      };
    }
    if (ledger.isRequestSatisfied.answer) {
      state.status = "completed";
      const lastOutput2 = Object.values(state.agentOutputs).pop() || "";
      return { success: true, output: lastOutput2, results, rounds: round };
    }
    state.stallCount = detectStall(ledger, state.stallCount);
    if (shouldReplan(state.stallCount, config.maxStalls)) {
      state.stallCount = 0;
      try {
        const replanPrompt = buildReplanPrompt(state, agents);
        const replanResponse = await window.api.ai.chat(
          [{ role: "user", content: replanPrompt }],
          { model: config.managerModel, provider: config.managerProvider }
        );
        const newPlan = parsePlanResponse(replanResponse);
        if (newPlan) {
          state.plan = newPlan.steps.join("\n");
          state.facts = newPlan.facts;
        }
      } catch {
      }
      continue;
    }
    const nextAgentId = ledger.nextSpeaker.answer;
    const agent = agentMap.get(nextAgentId);
    if (!agent) {
      const fallback = agents[0];
      if (!fallback) throw new AgentError("No agents available");
      await executeAgent(fallback, ledger.instructionOrQuestion.answer, state, results, signal);
    } else {
      await executeAgent(agent, ledger.instructionOrQuestion.answer, state, results, signal);
    }
  }
  state.status = "failed";
  const lastOutput = Object.values(state.agentOutputs).pop() || "Max rounds reached";
  return { success: false, output: lastOutput, results, rounds: config.maxRounds };
}
async function executeAgent(agent, instruction, state, results, signal) {
  const tools = agent.tools.map((name) => getTool(name)).filter((t) => t !== void 0);
  const systemPrompt = buildAgentSystemPromptFromDef(agent, tools);
  const agentContext = getAgentContext(state, agent.id);
  const taskPrompt = buildTaskPromptForAgent(agent, instruction || state.task, state);
  const messages = [
    { role: "system", content: systemPrompt }
  ];
  if (agentContext) {
    messages.push({ role: "system", content: `Team context:
${agentContext}` });
  }
  messages.push({ role: "user", content: taskPrompt });
  addMessage(state, { from: "orchestrator", to: agent.id, type: "task", content: instruction });
  let finalOutput = "";
  let iterations = 0;
  for (let i = 0; i < agent.maxIterations; i++) {
    if (signal?.aborted) throw new AgentError("Aborted");
    iterations++;
    let llmOutput;
    try {
      llmOutput = await window.api.ai.chat(messages, { model: agent.model, provider: agent.provider });
    } catch (error) {
      const msg = error instanceof Error ? error.message : "LLM failed";
      const result2 = { agentId: agent.id, output: `Error: ${msg}`, success: false, iterations };
      addTaskResult(state, result2);
      results.push(result2);
      return;
    }
    const parsed = parseAgentOutput(llmOutput);
    if (parsed.type === "finish") {
      finalOutput = parsed.finalAnswer || parsed.thought;
      break;
    }
    if (parsed.type === "tool_call" && parsed.toolName) {
      messages.push({ role: "assistant", content: llmOutput });
      const tool = getTool(parsed.toolName);
      let toolResult = `Tool '${parsed.toolName}' not found`;
      if (tool?.handlerFn) {
        try {
          toolResult = await tool.handlerFn(parsed.toolArgs || {}, { pool: void 0, nodeId: agent.id, signal });
        } catch (e) {
          toolResult = `Error: ${e instanceof Error ? e.message : "Tool failed"}`;
        }
      }
      messages.push({ role: "user", content: buildToolResultPrompt(parsed.toolName, toolResult) });
      continue;
    }
    messages.push({ role: "assistant", content: llmOutput });
    messages.push({ role: "user", content: "Please use a tool or FINISH." });
  }
  if (!finalOutput) finalOutput = "Agent did not produce a final answer.";
  const result = { agentId: agent.id, output: finalOutput, success: true, iterations };
  addTaskResult(state, result);
  setAgentOutput(state, agent.id, finalOutput);
  addMessage(state, { from: agent.id, to: "orchestrator", type: "result", content: finalOutput });
  results.push(result);
}
let toolsRegistered = false;
class AgentOrchestratorNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "agent-orchestrator";
  }
  getMetadata() {
    return {
      type: "agent-orchestrator",
      label: "Agent Orchestrator",
      icon: "team",
      category: "agent",
      description: "Manage a team of agents. Sequential or hierarchical process.",
      inputs: [
        { name: "task", label: "Task", type: "string", required: true },
        { name: "context", label: "Context", type: "string", required: false }
      ],
      outputs: [
        { name: "output", label: "Output", type: "string", required: false },
        { name: "results", label: "Results", type: "array", required: false },
        { name: "rounds", label: "Rounds", type: "number", required: false }
      ],
      defaultConfig: {
        process: "sequential",
        planning: false,
        max_rounds: 15,
        max_stalls: 3,
        manager_model: "gpt-4o",
        manager_provider: "openai",
        agents: []
      }
    };
  }
  async run(inputs, config, _pool, context) {
    if (!toolsRegistered) {
      registerBuiltinTools();
      toolsRegistered = true;
    }
    const cfg = config;
    const task = String(inputs.task || cfg.task || "");
    const contextStr = inputs.context ? String(inputs.context) : "";
    const processType = cfg.process || "sequential";
    const expectedOutput = String(cfg.expected_output || "Complete the task");
    if (!task) {
      throw new NodeExecutionError(context.nodeId, this.type, "Task is required");
    }
    const agents = (cfg.agents || []).map((a) => createAgent(a));
    if (agents.length === 0) {
      throw new NodeExecutionError(context.nodeId, this.type, "At least one agent is required");
    }
    const fullTask = contextStr ? `${task}

Context:
${contextStr}` : task;
    const state = createTeamState(fullTask, expectedOutput);
    try {
      if (processType === "hierarchical") {
        const hierConfig = {
          managerModel: cfg.manager_model || "gpt-4o",
          managerProvider: cfg.manager_provider || "openai",
          maxRounds: cfg.max_rounds || 15,
          maxStalls: cfg.max_stalls || 3,
          planning: cfg.planning || false
        };
        const result2 = await runHierarchical(agents, state, hierConfig, context.signal);
        return {
          output: result2.output,
          results: result2.results,
          rounds: result2.rounds
        };
      }
      const result = await runSequential(agents, state, context.signal);
      return {
        output: result.output,
        results: result.results,
        rounds: result.results.length
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Orchestrator failed";
      throw new AgentError(`Orchestrator error: ${message}`, { cause: error });
    }
  }
}
class ShellNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "shell";
  }
  getMetadata() {
    return {
      type: "shell",
      label: "Shell",
      icon: "code",
      category: "tools",
      description: "Execute a shell command in sandbox.",
      inputs: [
        { name: "command", label: "Command", type: "string", required: true }
      ],
      outputs: [
        { name: "stdout", label: "Stdout", type: "string", required: false },
        { name: "stderr", label: "Stderr", type: "string", required: false },
        { name: "exit_code", label: "Exit Code", type: "number", required: false }
      ],
      defaultConfig: { timeout_ms: 3e4 }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const command = String(inputs.command || cfg.command || "");
    if (!command) throw new NodeExecutionError(context.nodeId, this.type, "Command is required");
    try {
      const sandbox = await createSandbox({ workflowId: context.nodeId, runId: `shell-${context.nodeId}` });
      const result = await sandbox.exec(command, {
        timeoutMs: cfg.timeout_ms || 3e4,
        cwd: cfg.cwd
      });
      return { stdout: result.stdout, stderr: result.stderr, exit_code: result.exitCode };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Shell execution failed";
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error });
    }
  }
}
class ManualTriggerNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "manual-trigger";
  }
  getMetadata() {
    return {
      type: "manual-trigger",
      label: "Manual Trigger",
      icon: "play-circle",
      category: "trigger",
      description: "User-initiated workflow execution with input form.",
      inputs: [],
      outputs: [],
      defaultConfig: { variables: [] }
    };
  }
  async run(_inputs, config, pool, context) {
    const cfg = config;
    const result = {};
    for (const v of cfg.variables || []) {
      const value = pool.get([context.nodeId, v.name]) ?? v.default ?? "";
      pool.set([context.nodeId, v.name], value);
      result[v.name] = value;
    }
    return result;
  }
}
class WebhookTriggerNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "webhook-trigger";
  }
  getMetadata() {
    return {
      type: "webhook-trigger",
      label: "Webhook Trigger",
      icon: "global",
      category: "trigger",
      description: "HTTP webhook endpoint. POST body as input.",
      inputs: [],
      outputs: [
        { name: "body", label: "Request Body", type: "string", required: false },
        { name: "headers", label: "Headers", type: "object", required: false },
        { name: "method", label: "Method", type: "string", required: false }
      ],
      defaultConfig: { path: "/webhook", method: "POST" }
    };
  }
  async run(_inputs, _config, _pool, _context) {
    return { body: "", headers: {}, method: "POST" };
  }
}
class ScheduleTriggerNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "schedule-trigger";
  }
  getMetadata() {
    return {
      type: "schedule-trigger",
      label: "Schedule Trigger",
      icon: "clock-circle",
      category: "trigger",
      description: "Cron-based scheduled workflow execution.",
      inputs: [],
      outputs: [
        { name: "timestamp", label: "Timestamp", type: "string", required: false }
      ],
      defaultConfig: { cron: "0 * * * *" }
    };
  }
  async run(_inputs, _config, _pool, _context) {
    return { timestamp: (/* @__PURE__ */ new Date()).toISOString() };
  }
}
class FileWriteNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "file-write";
  }
  getMetadata() {
    return {
      type: "file-write",
      label: "File Write",
      icon: "file-text",
      category: "tools",
      description: "Write content to a file in the sandbox.",
      inputs: [
        { name: "path", label: "File Path", type: "string", required: true },
        { name: "content", label: "Content", type: "string", required: true }
      ],
      outputs: [
        { name: "path", label: "Written Path", type: "string", required: false },
        { name: "bytes", label: "Bytes Written", type: "number", required: false }
      ],
      defaultConfig: { create_dirs: true }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const filePath = String(inputs.path || cfg.path || "");
    const content = String(inputs.content || cfg.content || "");
    if (!filePath) throw new NodeExecutionError(context.nodeId, this.type, "File path is required");
    try {
      const sandbox = await createSandbox({ workflowId: context.nodeId, runId: `fw-${context.nodeId}` });
      await sandbox.writeFile(filePath, content);
      return { path: filePath, bytes: content.length };
    } catch (error) {
      const message = error instanceof Error ? error.message : "File write failed";
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error });
    }
  }
}
class SubWorkflowNode extends BaseNode {
  constructor() {
    super(...arguments);
    this.type = "sub-workflow";
  }
  getMetadata() {
    return {
      type: "sub-workflow",
      label: "Sub-Workflow",
      icon: "apartment",
      category: "agent",
      description: "Embed another workflow as a node. Pass inputs, get outputs.",
      inputs: [
        { name: "input", label: "Input", type: "string", required: false }
      ],
      outputs: [
        { name: "output", label: "Output", type: "string", required: false }
      ],
      defaultConfig: { workflow_id: "", inputs: {} }
    };
  }
  async run(inputs, config, _pool, context) {
    const cfg = config;
    const workflowId = cfg.workflow_id;
    if (!workflowId) {
      throw new NodeExecutionError(context.nodeId, this.type, "workflow_id is required");
    }
    try {
      const workflow = await window.api.workflow.load(workflowId);
      if (!workflow) {
        throw new NodeExecutionError(context.nodeId, this.type, `Workflow '${workflowId}' not found`);
      }
      const result = await window.api.workflow.run(workflow, {
        inputs: { ...cfg.inputs, ...inputs }
      });
      if (result.success) {
        const lastResult = result.results?.[result.results.length - 1];
        return { output: lastResult?.output ? String(lastResult.output) : "" };
      } else {
        throw new NodeExecutionError(context.nodeId, this.type, result.error || "Sub-workflow failed");
      }
    } catch (error) {
      if (error instanceof NodeExecutionError) throw error;
      const message = error instanceof Error ? error.message : "Sub-workflow execution failed";
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error });
    }
  }
}
const registry = /* @__PURE__ */ new Map([
  ["start", StartNode],
  ["end", EndNode],
  ["llm", LLMNode],
  ["code", CodeNode],
  ["condition", ConditionNode],
  ["http-request", HTTPRequestNode],
  ["template", TemplateNode],
  ["iteration", IterationNode],
  ["loop", LoopNode],
  ["variable-aggregator", VariableAggregatorNode],
  ["variable-assigner", VariableAssignerNode],
  ["knowledge-retrieval", KnowledgeRetrievalNode],
  ["parameter-extractor", ParameterExtractorNode],
  ["question-classifier", QuestionClassifierNode],
  ["file-explorer", FileExplorerNode],
  ["file-reader", FileReaderNode],
  ["context-loader", ContextLoaderNode],
  ["react-agent", ReActAgentNode],
  ["agent-orchestrator", AgentOrchestratorNode],
  ["shell", ShellNode],
  ["manual-trigger", ManualTriggerNode],
  ["webhook-trigger", WebhookTriggerNode],
  ["schedule-trigger", ScheduleTriggerNode],
  ["file-write", FileWriteNode],
  ["sub-workflow", SubWorkflowNode]
]);
const originalCreate = NodeFactory.create;
NodeFactory.create = (type) => {
  const cls = registry.get(type);
  if (cls) return new cls();
  return originalCreate(type);
};
const originalHas = NodeFactory.has;
NodeFactory.has = (type) => {
  return registry.has(type) || originalHas(type);
};
const originalGetRegisteredTypes = NodeFactory.getRegisteredTypes;
NodeFactory.getRegisteredTypes = () => {
  return [.../* @__PURE__ */ new Set([...originalGetRegisteredTypes(), ...registry.keys()])];
};
let mainWindow$1 = null;
function setMainWindow(win) {
  mainWindow$1 = win;
}
function sendEvent(event) {
  if (mainWindow$1 && !mainWindow$1.isDestroyed()) {
    mainWindow$1.webContents.send("workflow:event", event);
  }
}
function registerWorkflowRunnerHandlers() {
  electron.ipcMain.handle("workflow:run", async (_event, dsl, options) => {
    try {
      const graph = deserializeGraph(dsl);
      const pool = new VariablePool();
      if (options?.inputs) {
        for (const [key, value] of Object.entries(options.inputs)) {
          pool.set(["start", key], value);
        }
      }
      const uiLayer = new UILayer((event) => sendEvent(event));
      const engine = new GraphEngine({
        graph,
        variablePool: pool,
        layers: [uiLayer],
        maxSteps: options?.maxSteps || 1e3,
        maxTimeMs: options?.maxTimeMs || 6e5
      });
      const results = [];
      for await (const event of engine.runSequential()) {
        results.push(event);
        sendEvent(event);
      }
      return { success: true, results };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      sendEvent({ type: "graph:error", error: message, timestamp: Date.now() });
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("workflow:stop", async (_event, runId) => {
    sendEvent({ type: "graph:aborted", runId, timestamp: Date.now() });
    return true;
  });
  electron.ipcMain.handle("workflow:run:status", async (_event, runId) => {
    return { runId, status: "unknown" };
  });
}
function registerSandboxHandlers() {
  electron.ipcMain.handle("sandbox:create", async (_event, config) => {
    try {
      const sandbox = await createSandbox(config);
      return { success: true, id: sandbox.id, rootPath: sandbox.rootPath };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to create sandbox";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("sandbox:destroy", async (_event, workflowId, runId) => {
    try {
      await destroySandbox(workflowId, runId);
      return { success: true };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to destroy sandbox";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("sandbox:exec", async (_event, workflowId, command, options) => {
    try {
      const sandbox = getSandbox(workflowId);
      if (!sandbox) throw new Error("Sandbox not found");
      const result = await sandbox.exec(command, options);
      return { success: true, ...result };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Execution failed";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("sandbox:execCode", async (_event, workflowId, language, code) => {
    try {
      const sandbox = getSandbox(workflowId);
      if (!sandbox) throw new Error("Sandbox not found");
      const result = await sandbox.execCode(language, code);
      return { success: true, ...result };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Code execution failed";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("sandbox:readFile", async (_event, workflowId, filePath) => {
    try {
      const sandbox = getSandbox(workflowId);
      if (!sandbox) throw new Error("Sandbox not found");
      const content = await sandbox.readFile(filePath);
      return { success: true, content };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Read failed";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("sandbox:writeFile", async (_event, workflowId, filePath, content) => {
    try {
      const sandbox = getSandbox(workflowId);
      if (!sandbox) throw new Error("Sandbox not found");
      await sandbox.writeFile(filePath, content);
      return { success: true };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Write failed";
      return { success: false, error: message };
    }
  });
}
function registerDSLHandlers() {
  electron.ipcMain.handle("dsl:export", async (_event, dsl) => {
    try {
      const result = await electron.dialog.showSaveDialog({
        title: "Export Workflow",
        defaultPath: `${dsl.name || "workflow"}.json`,
        filters: [{ name: "JSON", extensions: ["json"] }]
      });
      if (result.canceled || !result.filePath) return { success: false, error: "Cancelled" };
      await promises.writeFile(result.filePath, JSON.stringify(dsl, null, 2), "utf-8");
      return { success: true, path: result.filePath };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Export failed";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("dsl:import", async () => {
    try {
      const result = await electron.dialog.showOpenDialog({
        title: "Import Workflow",
        filters: [{ name: "JSON", extensions: ["json"] }],
        properties: ["openFile"]
      });
      if (result.canceled || result.filePaths.length === 0) return { success: false, error: "Cancelled" };
      const content = await promises.readFile(result.filePaths[0], "utf-8");
      const dsl = JSON.parse(content);
      return { success: true, dsl };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Import failed";
      return { success: false, error: message };
    }
  });
}
function registerMemoryHandlers() {
  electron.ipcMain.handle("memory:search", async (_event, workflowId, query, options) => {
    try {
      const memory = getOrCreateMemory(workflowId);
      const k = options?.k || 5;
      const layer = options?.layer || "all";
      const results = [];
      if (layer === "all" || layer === "semantic") {
        const semantic = await memory.searchSemantic(query, k);
        results.push(...semantic.map((r) => ({ type: "semantic", ...r })));
      }
      if (layer === "all" || layer === "episodic") {
        const episodic = await memory.searchEpisodic(query, k);
        results.push(...episodic.map((r) => ({ type: "episodic", ...r })));
      }
      if (layer === "all" || layer === "procedural") {
        const procedural = await memory.searchProcedural(query, k);
        results.push(...procedural.map((r) => ({ type: "procedural", ...r })));
      }
      return { success: true, results };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Search failed";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("memory:addSemantic", async (_event, workflowId, content, type, metadata) => {
    try {
      const memory = getOrCreateMemory(workflowId);
      const id = await memory.addSemantic(content, type, metadata);
      return { success: true, id };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Add failed";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("memory:recordOutcome", async (_event, workflowId, outcome, feedback) => {
    try {
      const memory = getOrCreateMemory(workflowId);
      const id = await memory.recordOutcome(outcome, feedback);
      return { success: true, id };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Record failed";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("memory:stats", async (_event, workflowId) => {
    try {
      const memory = getOrCreateMemory(workflowId);
      return { success: true, stats: memory.getStats() };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Stats failed";
      return { success: false, error: message };
    }
  });
  electron.ipcMain.handle("memory:consolidate", async (_event, workflowId) => {
    try {
      const memory = getOrCreateMemory(workflowId);
      const result = await memory.consolidate();
      return { success: true, result };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Consolidate failed";
      return { success: false, error: message };
    }
  });
}
let mainWindow = null;
function createWindow() {
  const isDev = !electron.app.isPackaged;
  mainWindow = new electron.BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  setMainWindow(mainWindow);
  mainWindow.on("ready-to-show", () => {
    mainWindow?.show();
  });
  mainWindow.webContents.setWindowOpenHandler((details) => {
    electron.shell.openExternal(details.url);
    return { action: "deny" };
  });
  if (isDev && process.env["ELECTRON_RENDERER_URL"]) {
    mainWindow.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }
}
electron.app.whenReady().then(() => {
  const dbPath = path.join(electron.app.getPath("userData"), "evolux.db");
  openDatabase(dbPath);
  createWindow();
  registerAIHandlers();
  registerWorkflowHandlers();
  registerWorkflowRunnerHandlers();
  registerSandboxHandlers();
  registerDSLHandlers();
  registerMemoryHandlers();
  electron.app.on("activate", function() {
    if (electron.BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});
electron.app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    electron.app.quit();
  }
});
