// Types for the evo engine's JSONL RPC protocol (see crates/evo-protocol).
// Only the fields the UI reads are typed; everything else stays open.

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

/** Any line the engine writes to stdout. */
export interface EngineMessage {
  type: string;
  [key: string]: any;
}

export interface ResponseMessage extends EngineMessage {
  type: "response";
  id?: string;
  command: string;
  success: boolean;
  data?: any;
  error?: string;
}

export interface ContentPart {
  type: string;
  text?: string;
  thinking?: string;
  [key: string]: any;
}

export interface AgentMessage {
  role: "user" | "assistant" | "toolResult" | string;
  content: ContentPart[] | string;
  stopReason?: string;
  errorMessage?: string;
  model?: string;
  provider?: string;
  usage?: { input: number; output: number; totalTokens: number };
}

export interface ModelDescriptor {
  id: string;
  name: string;
  api: string;
  provider: string;
  reasoning: boolean;
  contextWindow: number;
  maxTokens: number;
}

export interface EngineState {
  modelId?: string;
  model?: string;
  provider?: string;
  thinkingLevel?: string;
  activeTools?: string[];
  context?: { tokens: number; window: number; percent: number };
}

/** Concatenate the text parts of a message. */
export function messageText(message: AgentMessage | undefined): string {
  if (!message) return "";
  if (typeof message.content === "string") return message.content;
  return message.content
    .filter((part) => part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("");
}

/** Concatenate the thinking parts of a message. */
export function messageThinking(message: AgentMessage | undefined): string {
  if (!message || typeof message.content === "string") return "";
  return message.content
    .filter((part) => part.type === "thinking" && typeof part.thinking === "string")
    .map((part) => part.thinking)
    .join("");
}

// ── Providers (`get_providers`, `set_provider`, `remove_provider`, `refresh_provider_models`) ──

export type ProviderKind = "api_key" | "oauth" | "local" | "cloud";

/** One credential field. Secret values never leave the engine. */
export interface ProviderField {
  /** `apiKey`, `baseUrl`, or a provider-specific field (`region`, `accessKeyId`, `deployments`…). */
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
  /** Environment variable the engine also reads for this field. */
  env?: string | null;
  /** A key is saved (its value is not sent). */
  hasValue?: boolean;
  /** No key is saved, but this environment variable supplies one. */
  fromEnv?: string | null;
  /** Saved non-secret value (the base-URL override). */
  value?: string | null;
  placeholder?: string;
}

export interface ProviderRow {
  id: string;
  label: string;
  description: string;
  kind: ProviderKind;
  api: string;
  /** `curated` (hand-maintained) or `catalog` (models.dev long tail). */
  source: "curated" | "catalog" | string;
  supported: boolean;
  unsupportedReason?: string | null;
  recommended: boolean;
  rank: number;
  docsUrl: string;
  modelsDocUrl: string;
  baseUrl: string;
  connected: boolean;
  status?: "missing" | "ready" | "expired" | "anonymous" | null;
  credentialSource?: string | null;
  modelCount: number;
  discoveredAt?: number | null;
  discoveryError?: string | null;
  /** Sign-in flow (`codex`, `copilot`) instead of a key. */
  login?: string | null;
  loginState?: LoginState | null;
  /** Signed-in account (email or GitHub login). */
  account?: string | null;
  /** A sign-in that creates an API key (`xiaomi`), offered beside the key field. */
  keyLogin?: string | null;
  /** The provider reports plan usage (`get_provider_usage`). */
  usage?: boolean;
  fields: ProviderField[];
}

/** One limit of a subscription plan. */
export interface UsageLimit {
  id: string;
  name: string;
  /** 0–100. */
  usedPercent?: number | null;
  windowMinutes?: number | null;
  /** Unix seconds. */
  resetsAt?: number | null;
  used?: number | null;
  total?: number | null;
  unlimited: boolean;
  reached: boolean;
}

/** `get_provider_usage`. */
export interface ProviderUsage {
  provider: string;
  plan?: string | null;
  limits: UsageLimit[];
}

export interface LoginState {
  status: "pending" | "success" | "error";
  /** Page to open: the sign-in page, or GitHub's device page. */
  url?: string;
  /** Code to enter on GitHub's device page. */
  userCode?: string;
  error?: string;
  account?: string;
}

/** Where the model database in use came from. */
export interface ModelsDevStatus {
  source: "models.dev" | "bundled";
  fetchedAt?: number | null;
  checkedAt?: number | null;
  modelCount: number;
}

export interface ProvidersList {
  providers: ProviderRow[];
  recommended: string[];
  connected: number;
  modelsDev?: ModelsDevStatus;
}

export interface ProviderMutation {
  provider: ProviderRow | null;
  discovery?: { ok: boolean; modelCount?: number; skipped?: boolean; error?: string };
  reload?: {
    provider?: string;
    modelId?: string;
    modelChanged?: boolean;
    unconfigured?: boolean;
    modelCount?: number;
    error?: string;
    requiresRestart?: boolean;
  };
}

/** Provider id of the engine's placeholder when no provider is connected. */
export const UNCONFIGURED_PROVIDER = "unconfigured";

// ── Context window (`get_context_breakdown`) ────────────────────────────────

export interface ContextCategory {
  id: "messages" | "system_tools" | "plugin_tools" | "system_prompt" | "context_files" | "skills" | "autocompact_buffer" | "free" | string;
  label: string;
  tokens: number;
  percent: number;
}

export interface ContextBreakdown {
  window: number;
  total: number;
  percent: number;
  /** A character estimate until the provider reports a prompt size. */
  estimated: boolean;
  compactionEnabled: boolean;
  untilCompact: number | null;
  categories: ContextCategory[];
  tools: { name: string; tokens: number; source: "builtin" | "plugin" }[];
  skills: { name: string; tokens: number }[];
  contextFiles: { path: string; tokens: number }[];
}
