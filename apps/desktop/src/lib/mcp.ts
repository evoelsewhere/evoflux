// Connectors: the shell's MCP pool (src-tauri/src/mcp.rs, crates/evo-mcp).

import { invoke } from "@tauri-apps/api/core";

export type ConnectorStatus = "off" | "connecting" | "connected" | "needs-auth" | "failed";
export type ToolPermission = "allow" | "ask" | "block";

export interface ConnectorConfig {
  type?: "stdio" | "http" | "sse";
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
  url?: string;
  headers?: Record<string, string>;
  disabled?: boolean;
  toolPermissions?: Record<string, ToolPermission>;
  [key: string]: unknown;
}

export interface ConnectorTool {
  name: string;
  title?: string | null;
  description?: string | null;
  readOnly: boolean;
  permission: ToolPermission;
  /** What chats call it: `mcp__<server>__<tool>`. */
  exposedName: string;
}

export interface ConnectorPrompt {
  name: string;
  title?: string;
  description?: string;
  arguments?: { name: string; description?: string; required?: boolean }[];
}

export interface ConnectorResource {
  uri: string;
  name?: string;
  description?: string;
  mimeType?: string;
}

export interface Connector {
  /** The pool's id: the name, or `name#project` for a project's server. */
  key: string;
  name: string;
  /** The project root whose `.mcp.json` it comes from; `null`: your own. */
  project?: string | null;
  /** A URL connector with a saved sign-in. */
  signedIn?: boolean;
  resources: ConnectorResource[];
  kind: "stdio" | "http" | "sse" | "invalid";
  /** The command or URL. */
  summary: string;
  config: ConnectorConfig;
  status: ConnectorStatus;
  error?: string | null;
  server?: { name?: string; title?: string; version?: string } | null;
  instructions?: string | null;
  tools: ConnectorTool[];
  prompts: ConnectorPrompt[];
  log: string[];
}

export interface ProjectServer {
  name: string;
  summary: string;
  kind: "stdio" | "http";
  approval: "approved" | "denied" | "pending";
  key: string;
  /** One of your own connectors has the same name (yours is used). */
  shadowed: boolean;
}

export interface ProjectState {
  root: string | null;
  file?: string;
  error?: string | null;
  servers: ProjectServer[];
}

export interface ChatTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  permission: ToolPermission;
  server: string;
  tool: string;
}

/** The change event the shell emits. */
export const MCP_CHANGED = "mcp://changed";

export const mcp = {
  state: () => invoke<{ servers: Connector[]; path: string }>("mcp_state"),
  upsert: (name: string, config: ConnectorConfig, previous?: string) =>
    invoke<void>("mcp_upsert", { name, config, previous: previous ?? null }),
  remove: (name: string) => invoke<void>("mcp_remove", { name }),
  setEnabled: (name: string, on: boolean) => invoke<void>("mcp_set_enabled", { name, on }),
  reconnect: (name: string) => invoke<void>("mcp_reconnect", { name }),
  setPermission: (name: string, tool: string, permission: ToolPermission) =>
    invoke<void>("mcp_set_permission", { name, tool, permission }),
  chatTools: (cwd?: string) => invoke<ChatTool[]>("mcp_chat_tools", { cwd: cwd ?? null }),
  call: (name: string, args: Record<string, unknown> | undefined, cwd?: string) =>
    invoke<Record<string, unknown>>("mcp_call", { name, arguments: args ?? null, cwd: cwd ?? null }),
  /** Opens the provider's sign-in page; resolves once the browser came back. */
  signIn: (name: string) => invoke<void>("mcp_sign_in", { name }),
  signOut: (name: string) => invoke<void>("mcp_sign_out", { name }),
  projectState: (cwd: string) => invoke<ProjectState>("mcp_project_state", { cwd }),
  openProject: (cwd: string) => invoke<void>("mcp_open_project", { cwd }),
  setProjectApproval: (cwd: string, name: string, approved: boolean) =>
    invoke<void>("mcp_set_project_approval", { cwd, name, approved }),
  readResource: (server: string, uri: string) => invoke<string>("mcp_read_resource", { server, uri }),
  getPrompt: (server: string, prompt: string, args: Record<string, string>) =>
    invoke<string>("mcp_get_prompt", { server, prompt, arguments: args }),
};

/** `mcp__<server>__<tool>` names a connector's tool. */
export const isMcpTool = (name: string) => name.startsWith("mcp__");

/** `server · tool` for a tool row. */
export function mcpToolLabel(name: string): { server: string; tool: string } {
  const [, server = "", ...rest] = name.split("__");
  return { server, tool: rest.join("__") };
}

// ── Tool search ──────────────────────────────────────────────────────────────
//
// Many connector tools crowd the model's context. Past a threshold a chat gets
// two tools instead of every connector tool: `mcp_search_tools` finds tools
// (with their input schemas) and `mcp_call_tool` runs one by name. Each call
// still goes through the tool's own permission (allow / ask / block).

export const MCP_SEARCH_TOOL = "mcp_search_tools";
export const MCP_CALL_TOOL = "mcp_call_tool";
/** Defer past this many tools… */
const DEFER_COUNT = 40;
/** …or this many characters of names, descriptions and schemas. */
const DEFER_CHARS = 60_000;

/** Whether `tools` should sit behind search rather than be listed. */
export function shouldDefer(tools: ChatTool[]): boolean {
  if (tools.length > DEFER_COUNT) return true;
  const size = tools.reduce((n, t) => n + t.name.length + t.description.length + JSON.stringify(t.inputSchema).length, 0);
  return size > DEFER_CHARS;
}

/** The two tools a chat gets instead of `tools`. */
export function searchToolDefinitions(tools: ChatTool[]) {
  const servers = new Map<string, number>();
  for (const tool of tools) {
    const server = mcpToolLabel(tool.name).server;
    servers.set(server, (servers.get(server) ?? 0) + 1);
  }
  const listing = [...servers].map(([server, count]) => `${server} (${count})`).join(", ");
  return [
    {
      name: MCP_SEARCH_TOOL,
      description:
        `Find tools of the connected MCP servers — ${listing} — and get their input schemas. ` +
        `Search by what you want to do ("create issue", "query database"), or pass "select:<name>,<name>" for exact tool names. ` +
        `Then run one with ${MCP_CALL_TOOL}.`,
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: 'Words describing the task, or "select:name1,name2".' },
          limit: { type: "number", description: "At most this many results (default 8)." },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
    {
      name: MCP_CALL_TOOL,
      description: `Run a connector tool found with ${MCP_SEARCH_TOOL}, by its full name (mcp__server__tool), with arguments matching its input schema.`,
      inputSchema: {
        type: "object",
        properties: {
          name: { type: "string", description: "The tool's full name, e.g. mcp__github__create_issue." },
          arguments: { type: "object", description: "The tool's arguments." },
        },
        required: ["name"],
        additionalProperties: false,
      },
    },
  ];
}

/** The best matches for `query` among `tools`. */
export function searchTools(tools: ChatTool[], query: string, limit = 8): ChatTool[] {
  const q = query.trim();
  if (q.toLowerCase().startsWith("select:")) {
    const names = q.slice(7).split(",").map((n) => n.trim()).filter(Boolean);
    return tools.filter((t) => names.includes(t.name) || names.includes(mcpToolLabel(t.name).tool));
  }
  const words = q.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 1);
  if (!words.length) return tools.slice(0, limit);
  return tools
    .map((tool) => {
      const name = tool.name.toLowerCase();
      const description = tool.description.toLowerCase();
      const score = words.reduce((s, w) => s + (name.includes(w) ? 3 : 0) + (description.includes(w) ? 1 : 0), 0);
      return { tool, score };
    })
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score || a.tool.name.localeCompare(b.tool.name))
    .slice(0, Math.max(1, Math.min(limit, 25)))
    .map((x) => x.tool);
}
