import { fetchWithTimeout, parseDetailOrThrow } from './_shared'
import { apiBaseUrl } from '../base-url'

async function voiceRequestError(response: Response, label: string): Promise<never> {
  let detail: unknown
  try {
    detail = (await response.json())?.detail
  } catch {
    // Keep a safe status-only message if the server did not return JSON.
  }
  if (detail && typeof detail === 'object') {
    const body = detail as { message?: unknown; providers?: unknown }
    const failures = Array.isArray(body.providers)
      ? body.providers.flatMap((entry) => {
          if (!entry || typeof entry !== 'object') return []
          const failure = entry as { provider_id?: unknown; category?: unknown }
          return typeof failure.provider_id === 'string' && typeof failure.category === 'string'
            ? [`${failure.provider_id}: ${failure.category}`]
            : []
        })
      : []
    const message = typeof body.message === 'string' ? body.message : `${label} failed (${response.status})`
    throw new Error(`${message}${failures.length ? ` ${failures.join('; ')}.` : ''} Check Settings → Voice input.`)
  }
  throw new Error(typeof detail === 'string' ? detail : `${label} failed (${response.status}). Check Settings → Voice input.`)
}

export interface VoiceProviderProfile {
  id: string
  name: string
  adapter: 'openai_compatible' | 'deepgram' | 'azure_speech' | 'google_cloud' | 'local_faster_whisper'
  base_url: string
  models: string[]
  locale?: string | null
  enabled: boolean
  credential_configured?: boolean
  health?: { status: 'healthy' | 'degraded' | 'needs_attention'; last_failure: string | null; checked_at: string } | null
}

export interface VoiceRouteEntry {
  provider_id: string
  model_id: string
}

export interface VoiceSettings {
  providers: VoiceProviderProfile[]
  chain: VoiceRouteEntry[]
  allow_hosted_fallback: boolean
  local_private_only: boolean
  adapters: VoiceProviderProfile['adapter'][]
}

export async function getVoiceSettings(): Promise<VoiceSettings> {
  const res = await fetch(`${apiBaseUrl()}/voice/settings`)
  if (!res.ok) await parseDetailOrThrow(res, 'Load voice settings')
  return res.json()
}

export async function listVoiceProviderModels(providerId: string): Promise<{ models: string[] }> {
  const res = await fetch(`${apiBaseUrl()}/voice/providers/${encodeURIComponent(providerId)}/models`)
  if (!res.ok) await voiceRequestError(res, 'Load provider models')
  return res.json()
}

export async function saveVoiceSettings(input: {
  config: Omit<VoiceSettings, 'adapters'>
  credentials?: Record<string, string>
  clear_credentials?: string[]
}): Promise<VoiceSettings> {
  const res = await fetch(`${apiBaseUrl()}/voice/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...input,
      config: {
        ...input.config,
        providers: Object.fromEntries(input.config.providers.map((profile) => [profile.id, profile])),
      },
    }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'Save voice settings')
  return res.json()
}

export async function transcribeVoiceRecording(file: File, language?: string, signal?: AbortSignal): Promise<{
  text: string
  provider_id: string
  model_id: string
  fallback_used: boolean
}> {
  const form = new FormData()
  form.append('audio', file, file.name || 'recording.webm')
  if (language) form.append('language', language)
  const res = await fetchWithTimeout(`${apiBaseUrl()}/voice/transcribe`, { method: 'POST', body: form, signal }, 150_000)
  if (!res.ok) await voiceRequestError(res, 'Voice transcription')
  return res.json()
}

export async function testVoiceProvider(providerId: string, modelId: string, file: File): Promise<{
  ok: boolean
  provider_id: string
  model_id: string
  text: string
}> {
  const form = new FormData()
  form.append('audio', file, file.name || 'voice-provider-test.webm')
  form.append('model_id', modelId)
  const res = await fetchWithTimeout(`${apiBaseUrl()}/voice/providers/${encodeURIComponent(providerId)}/test`, { method: 'POST', body: form }, 90_000)
  if (!res.ok) await voiceRequestError(res, 'Voice provider test')
  return res.json()
}
