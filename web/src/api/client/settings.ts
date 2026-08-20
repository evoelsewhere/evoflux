/**
 * EvoFlux API client — settings group: sandbox, title, multimodal, providers, OAuth.
 */

import { apiBaseUrl } from '../base-url'
import { readSSE } from '../sse'
import type { SSECallbacks } from '../sse'
import { parseDetailOrThrow } from './_shared'
import type { ManagedResourceProvider } from '../types'

export type SandboxSettings = {
  denied_patterns: string[]
  worktree_location: 'repository' | 'user_data'
  inherit_shell_environment: boolean
  load_shell_profile: boolean
  outbound_data_policy: 'block' | 'redact' | 'off'
  outbound_pii_policy: 'off' | 'standard' | 'strict'
  max_execution_seconds: number
  max_output_bytes: number
}

export type SandboxSettingsUpdate = SandboxSettings

export type VersionControlSettings = {
  network_timeout_seconds: number
  max_diff_bytes: number
  default_pull_strategy: 'ff_only' | 'merge' | 'rebase'
  prune_on_fetch: boolean
  allow_force_push: boolean
  review_request_timeout_seconds: number
  review_retry_attempts: number
  review_retry_backoff_seconds: number
  review_max_concurrent_repositories: number
  review_max_pages_per_repository: number
  allow_review_mutations: boolean
  allow_insecure_connections: boolean
  require_successful_checks_before_merge: boolean
}

export async function getSandboxSettings(): Promise<SandboxSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/sandbox`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /settings/sandbox')
  return res.json()
}

export async function updateSandboxSettings(
  body: SandboxSettingsUpdate,
): Promise<SandboxSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/sandbox`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'PUT /settings/sandbox')
  return res.json()
}

export async function getVersionControlSettings(): Promise<VersionControlSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/version-control`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /settings/version-control')
  return res.json()
}

export async function updateVersionControlSettings(
  body: VersionControlSettings,
): Promise<VersionControlSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/version-control`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'PUT /settings/version-control')
  return res.json()
}

export type WebBridgeSettings = {
  enabled: boolean
  allow_evaluate: boolean
  built_in_allowed_domains: string[]
  built_in_blocked_domains: string[]
  built_in_allow_evaluate: boolean
  built_in_allow_storage: boolean
  built_in_allow_cookie_values: boolean
  built_in_allow_http_requests: boolean
  built_in_allow_clipboard_read: boolean
  built_in_allow_clipboard_write: boolean
  built_in_allow_file_uploads: boolean
  built_in_allow_downloads: boolean
  built_in_allow_agent_permission_accept: boolean
}

export async function getWebBridgeSettings(): Promise<WebBridgeSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/webbridge`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /settings/webbridge')
  return res.json()
}

export async function updateWebBridgeSettings(
  body: WebBridgeSettings,
): Promise<WebBridgeSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/webbridge`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'PUT /settings/webbridge')
  return res.json()
}

export type ConductorSettings = {
  enabled: boolean
  url: string
  machine_credential_path: string | null
  sync_interval_seconds: number
  heartbeat_interval_seconds: number
  request_timeout_seconds: number
  enforcement_mode: 'report' | 'enforce'
}

export type ConductorManagedResource = ManagedResourceProvider & {
  kind: 'agent' | 'skill' | 'plugin'
  slug: string
  state?: string
  message?: string | null
  trust_required?: boolean
  trust_review?: {
    executable_commands?: Array<{ server: string; executable: string; args: string[] }>
    remote_hosts?: Array<{ server: string; transport: string; host: string; url: string }>
    environment_fields?: string[]
    capabilities?: Array<{ name: string; source: string }>
  } | null
}

export type LegacyConductorResource = {
  project_id?: string
  resource_id?: string
  version_id?: string | null
  version?: string | null
  applied_version_id?: string | null
  applied_version?: string | null
  release_channel?: 'beta' | 'published' | null
  kind: 'agent' | 'skill' | 'mcp' | 'plugin'
  slug: string
  state: string
  observed_state?: string
  drift?: string[]
  message?: string | null
  trust_required?: boolean
  trust_review?: {
    executable_commands?: Array<{ server: string; executable: string; args: string[] }>
    remote_hosts?: Array<{ server: string; transport: string; host: string; url: string }>
    environment_fields?: string[]
    capabilities?: Array<{ name: string; source: string }>
  } | null
}

export type ConductorStatus = {
  enabled: boolean
  enrolled: boolean
  state: string
  installation_id: string | null
  project_id: string | null
  project_name: string | null
  project_display_name: string | null
  project_logo_url: string | null
  member_display_name: string | null
  member_primary_role: string | null
  collection_level: 'L0' | 'L1' | 'L2' | null
  heartbeat_interval_seconds: number
  last_heartbeat_at: string | null
  last_sync_at: string | null
  last_success_at: string | null
  manifest_revision: string | null
  offline: boolean
  maintenance_required: boolean
  error: string | null
  resources: Array<ConductorManagedResource | LegacyConductorResource>
  sync?: {
    heartbeat: ConductorSyncLaneStatus
    resources: ConductorSyncLaneStatus
    inventory: ConductorSyncLaneStatus
    telemetry: ConductorSyncLaneStatus
  }
  telemetry?: {
    pending_events: number
    capacity: number
    utilization_percent: number
    oldest_event_at: string | null
    pending_requests: number
    pending_model_calls: number
    pending_tool_calls: number
    attributed_events: number
    tokens_in: number
    tokens_out: number
    cache_read_tokens: number
    estimated_cost_usd_micros: number
    last_flush_accepted: number
    last_flush_duplicates: number
    delivery: ConductorTelemetryDeliverySummary | null
  }
}

export type ConductorTelemetryDeliverySummary = {
  installation_id: string
  window_days: number
  window_start: string
  window_end: string
  events: number
  requests: number
  model_calls: number
  tool_calls: number
  tokens_in: number
  tokens_out: number
  cache_read_tokens: number
  estimated_cost_usd_micros: number
  unpriced_model_calls: number
  attributed_events: number
  attributed_requests: number
  attributed_model_calls: number
  attributed_tool_calls: number
  attributed_estimated_cost_usd_micros: number
}

export type ConductorSyncLaneStatus = {
  state: 'idle' | 'syncing' | 'healthy' | 'offline' | 'paused' | 'error'
  last_attempt_at: string | null
  last_success_at: string | null
  error: string | null
}

export async function getConductorSettings(): Promise<ConductorSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/conductor`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /settings/conductor')
  return res.json()
}

export async function updateConductorSettings(body: ConductorSettings): Promise<ConductorSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/conductor`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'PUT /settings/conductor')
  return res.json()
}

export async function getConductorStatus(): Promise<ConductorStatus> {
  const res = await fetch(`${apiBaseUrl()}/settings/conductor/status`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /settings/conductor/status')
  return res.json()
}

export async function connectConductor(enrollmentToken: string): Promise<ConductorStatus> {
  const res = await fetch(`${apiBaseUrl()}/settings/conductor/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enrollment_token: enrollmentToken }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'POST /settings/conductor/connect')
  return res.json()
}

export async function disconnectConductor(): Promise<ConductorStatus> {
  const res = await fetch(`${apiBaseUrl()}/settings/conductor/disconnect`, { method: 'POST' })
  if (!res.ok) await parseDetailOrThrow(res, 'POST /settings/conductor/disconnect')
  return res.json()
}

export async function syncConductor(): Promise<ConductorStatus> {
  const res = await fetch(`${apiBaseUrl()}/settings/conductor/sync`, { method: 'POST' })
  if (!res.ok) await parseDetailOrThrow(res, 'POST /settings/conductor/sync')
  return res.json()
}

export async function approveConductorResource(resourceId: string): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/settings/conductor/resources/${encodeURIComponent(resourceId)}/approve`,
    { method: 'POST' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'POST /settings/conductor/resources/:id/approve')
}

export async function pullConductorResource(
  resourceId: string,
): Promise<ConductorManagedResource> {
  const res = await fetch(
    `${apiBaseUrl()}/settings/conductor/resources/${encodeURIComponent(resourceId)}/pull`,
    { method: 'POST' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'POST /settings/conductor/resources/:id/pull')
  return res.json()
}

export type MultimodalSectionSettings = {
  model: string
  [key: string]: string | number | boolean | null
}

export type MultimodalSettings = {
  image: MultimodalSectionSettings
  video: MultimodalSectionSettings
}

export async function getMultimodalSettings(): Promise<MultimodalSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/multimodal`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /settings/multimodal')
  return res.json()
}

export async function updateMultimodalSettings(
  body: MultimodalSettings,
): Promise<MultimodalSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/multimodal`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'PUT /settings/multimodal')
  return res.json()
}

// ── /settings/providers ──────────────────────────────────────────────────────

export type ProviderInfo = {
  id: string
  label: string
  description: string
  kind: 'api_key' | 'oauth' | 'local' | 'cloud_creds'
  credentials: Array<{
    name: string
    label: string
    secret: boolean
    required: boolean
    placeholder: string
  }>
  saved_credentials: Record<string, string>
  env_var: string
  env_vars: string[]
  fallback_models: string[]
  oauth_command: string
  docs_url: string
  is_configured: boolean
  is_saved: boolean
  is_reachable?: boolean | null
  visible_models: string[]
}

export type ProvidersListBody = {
  providers: ProviderInfo[]
  has_any_configured: boolean
}

export type ProviderSaveRequest = {
  api_key?: string
  extra?: Record<string, string>
}

export type ProviderModelsResponse = {
  provider: string
  models: string[]
  source: 'provider' | 'fallback'
}

export type ProviderUsageWindow = {
  used_percent: number
  window_minutes?: number | null
  resets_at?: number | null
}

export type ProviderUsageLimit = {
  limit_id?: string | null
  limit_name?: string | null
  primary?: ProviderUsageWindow | null
  secondary?: ProviderUsageWindow | null
  credits?: {
    has_credits: boolean
    unlimited: boolean
    balance?: string | null
    used?: string | null
    total?: string | null
  } | null
  plan_type?: string | null
  rate_limit_reached_type?: string | null
}

export type ProviderUsageResponse = {
  provider: string
  limits: ProviderUsageLimit[]
}

export type ProviderSaveResponse = {
  saved: boolean
  is_first_provider: boolean
}

export type ProviderVisibleModelsResponse = {
  provider: string
  visible_models: string[]
}

export type ProviderTestResponse = {
  ok: boolean
  latency_ms?: number | null
  error?: string | null
}

export type SeedInstallResponse = {
  agents_written: string[]
  skills_written: string[]
  configs_written: string[]
  source: string
}

export type OAuthLoginEvent = {
  event: string
  message?: string
  verification_uri?: string
  user_code?: string
  expires_in?: number
  elapsed_s?: number
  suggested_model?: string
  reason?: string
}

export async function listProviders(): Promise<ProvidersListBody> {
  const res = await fetch(`${apiBaseUrl()}/settings/providers`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /settings/providers')
  return res.json()
}

export async function saveProvider(
  providerId: string,
  body: ProviderSaveRequest,
): Promise<ProviderSaveResponse> {
  const res = await fetch(`${apiBaseUrl()}/settings/providers/${encodeURIComponent(providerId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, `PUT /settings/providers/${providerId}`)
  return res.json()
}

export async function testProvider(
  providerId: string,
  body: { api_key?: string; model: string; extra?: Record<string, string> },
): Promise<ProviderTestResponse> {
  const res = await fetch(`${apiBaseUrl()}/settings/providers/${encodeURIComponent(providerId)}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, `POST /settings/providers/${providerId}/test`)
  return res.json()
}

export async function listProviderModels(
  providerId: string,
  body: { api_key?: string; extra?: Record<string, string> },
): Promise<ProviderModelsResponse> {
  const res = await fetch(`${apiBaseUrl()}/settings/providers/${encodeURIComponent(providerId)}/models`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, `POST /settings/providers/${providerId}/models`)
  return res.json()
}

export async function saveProviderVisibleModels(
  providerId: string,
  models: string[],
): Promise<ProviderVisibleModelsResponse> {
  const res = await fetch(`${apiBaseUrl()}/settings/providers/${encodeURIComponent(providerId)}/visible-models`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ models }),
  })
  if (!res.ok) await parseDetailOrThrow(res, `PUT /settings/providers/${providerId}/visible-models`)
  return res.json()
}

export async function deleteProvider(providerId: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${apiBaseUrl()}/settings/providers/${encodeURIComponent(providerId)}`, {
    method: 'DELETE',
  })
  if (!res.ok) await parseDetailOrThrow(res, `DELETE /settings/providers/${providerId}`)
  return res.json()
}

export async function getProviderUsage(providerId: string): Promise<ProviderUsageResponse> {
  const res = await fetch(`${apiBaseUrl()}/settings/providers/${encodeURIComponent(providerId)}/usage`)
  if (!res.ok) await parseDetailOrThrow(res, `GET /settings/providers/${providerId}/usage`)
  return res.json()
}

export async function installSeed(providerModel: string): Promise<SeedInstallResponse> {
  const res = await fetch(`${apiBaseUrl()}/settings/seed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider_model: providerModel }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'POST /settings/seed')
  return res.json()
}

export function oauthLoginStream(
  providerId: string,
  callbacks: SSECallbacks & { onOAuthEvent?: (event: OAuthLoginEvent) => void },
  signal?: AbortSignal,
  mode?: 'browser',
): void {
  const query = mode ? `?mode=${encodeURIComponent(mode)}` : ''
  fetch(`${apiBaseUrl()}/auth/${encodeURIComponent(providerId)}/login${query}`, { signal })
    .then((res) => {
      if (!res.ok) throw new Error(`GET /auth/${providerId}/login failed: ${res.status}`)
      readSSE(res, {
        ...callbacks,
        onEvent: (type, data) => {
          const payload = data as Omit<OAuthLoginEvent, 'event'>
          callbacks.onOAuthEvent?.({ event: type, ...payload })
          callbacks.onEvent(type, data)
        },
      })
    })
    .catch((err) => { if (err.name !== 'AbortError') callbacks.onError?.(err) })
}

export async function submitOAuthCallback(providerId: string, code: string): Promise<{ ok: boolean; suggested_model?: string }> {
  const res = await fetch(`${apiBaseUrl()}/auth/${encodeURIComponent(providerId)}/callback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })
  if (!res.ok) await parseDetailOrThrow(res, `POST /auth/${providerId}/callback`)
  return res.json()
}
