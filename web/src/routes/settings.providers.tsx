import { useEffect, useMemo, useRef, useState } from 'react'
import fuzzysort from 'fuzzysort'
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  KeyRound,
  Loader2,
  Search,
  ShieldCheck,
  TerminalSquare,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiValidationError,
  installSeed,
  listProviderModels,
  oauthLoginStream,
  submitOAuthCallback,
  type OAuthLoginEvent,
  type ProviderInfo,
  type ProviderUsageLimit,
} from '@/api/client'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
} from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  queryKeys,
  useDeleteProviderMutation,
  useProviderModelsMutation,
  useProviderUsageQuery,
  useProvidersQuery,
  useSaveProviderMutation,
  useSaveProviderVisibleModelsMutation,
} from '@/queries'
import { openExternalUrl } from '@/lib/open-external'
import { useIsMobile } from '@/hooks/use-mobile'
import { usePlatform } from '@/hooks/use-platform'
import { mediumHapticFeedback } from '@/lib/haptics'
import { useToastStore } from '@/stores/useToastStore'
import { isTransientNetworkError } from '@/utils/errors'
import { cn } from '@/lib/utils'
import { ProviderBrandIcon as SharedProviderBrandIcon } from '@/components/providers/ProviderBrandIcon'

// ─── Constants ──────────────────────────────────────────────────────────────

const MODEL_LONG_PRESS_MS = 520
const MODEL_LONG_PRESS_MOVE_TOLERANCE = 10

function ProviderBrandIcon({ provider, size = 'md' }: { provider: ProviderInfo; size?: 'sm' | 'md' | 'lg' }) {
  return <SharedProviderBrandIcon providerId={provider.id} size={size} />
}

// ─── Utility helpers ─────────────────────────────────────────────────────────

function providerKindLabel(kind: ProviderInfo['kind']): string {
  if (kind === 'api_key') return 'API key'
  if (kind === 'oauth') return 'OAuth'
  if (kind === 'local') return 'Local'
  return 'Cloud'
}

const DAEMON_BASE_URL: Record<string, { var: string; placeholder: string }> = {
  anthropic: { var: 'ANTHROPIC_BASE_URL', placeholder: 'https://api.anthropic.com' },
  openai: { var: 'OPENAI_BASE_URL', placeholder: 'https://api.openai.com/v1' },
  router9: { var: 'ROUTER9_BASE_URL', placeholder: 'http://localhost:20128/v1' },
  cliproxy: { var: 'CLIPROXY_BASE_URL', placeholder: 'http://localhost:8317/v1' },
  ollama: { var: 'OLLAMA_BASE_URL', placeholder: 'http://localhost:11434/v1' },
  xiaomi: { var: 'XIAOMI_BASE_URL', placeholder: 'https://api.xiaomi.com/v1' },
  kimi: { var: 'MOONSHOT_BASE_URL', placeholder: 'https://api.kimi.ai/v1' },
  fci: { var: 'FCI_BASE_URL', placeholder: 'https://<your-fci-gateway>/v1' },
}

function eventLabel(event: OAuthLoginEvent): string {
  if (event.event === 'started') return 'Starting secure login'
  if (event.event === 'device_code') return 'Waiting for browser approval'
  if (event.event === 'polling' && typeof event.elapsed_s === 'number') return `Still waiting (${event.elapsed_s}s)`
  if (event.event === 'token_acquired') return 'Token received'
  if (event.event === 'verifying') return 'Verifying provider access'
  if (event.event === 'success') return 'Connected'
  if (event.event === 'failed') return 'Connection failed'
  return event.message || event.event.replaceAll('_', ' ')
}

function isBenignOAuthStreamClose(message: string): boolean {
  return isTransientNetworkError(new Error(message))
}

function formatResetTime(timestamp?: number | null): string | null {
  if (typeof timestamp !== 'number') return null
  return new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function usageLabel(limit: ProviderUsageLimit): string {
  if (limit.limit_name) return limit.limit_name
  if (limit.limit_id === 'codex') return 'Codex'
  return limit.limit_id || 'Usage'
}

function formatWindowDuration(minutes?: number | null): string {
  if (typeof minutes !== 'number') return 'window'
  if (minutes < 60) return `${minutes}m window`
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h window`
  return `${Math.round(minutes / (60 * 24))}d window`
}

function deviceCodeHelp(providerId: string): string {
  if (providerId === 'codex') {
    return 'Use this code for personal ChatGPT accounts. Keep this dialog open while the browser approves access.'
  }
  if (providerId === 'copilot') {
    return 'Use this code on GitHub to authorize Copilot. Keep this dialog open while GitHub approves access.'
  }
  return 'Use this code on the authorization page. Keep this dialog open while access is approved.'
}

// ─── Usage components ────────────────────────────────────────────────────────

function UsageBar({ label, window }: { label: string; window: NonNullable<ProviderUsageLimit['primary']> }) {
  const percent = Math.max(0, Math.min(100, window.used_percent))
  const reset = formatResetTime(window.resets_at)
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 text-xs text-(--color-text-muted)">
        <span>{label}</span>
        <span>{Math.round(percent)}% used{reset ? `, resets ${reset}` : ''}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-(--bg-key)">
        <div
          className="h-full rounded-full bg-(--color-accent)"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  )
}

function UsageLimitRows({ limit }: { limit: ProviderUsageLimit }) {
  const base = usageLabel(limit)
  const credits = limit.credits
  return (
    <>
      {limit.primary && (
        <UsageBar label={`${base} · ${formatWindowDuration(limit.primary.window_minutes)}`} window={limit.primary} />
      )}
      {limit.secondary && (
        <UsageBar label={`${base} · ${formatWindowDuration(limit.secondary.window_minutes)}`} window={limit.secondary} />
      )}
      {credits && !limit.primary && !limit.secondary && (
        <p className="text-xs text-(--color-text-muted)">
          {credits.unlimited ? 'Unlimited usage available' : credits.has_credits ? 'Usage credits available' : 'No usage credits available'}
        </p>
      )}
    </>
  )
}

function UsagePanel({ limits }: { limits: ProviderUsageLimit[] }) {
  if (limits.length === 0) return null
  const primary = limits[0]
  const credits = primary?.credits
  return (
    <div className="space-y-2 rounded-lg border border-(--color-border) bg-(--bg-page) p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-(--color-text)">Active usage</p>
        <p className="text-xs text-(--color-text-muted)">
          {primary?.plan_type ? `Plan: ${primary.plan_type}` : 'Live usage'}
          {credits?.unlimited ? ' · unlimited' : credits?.balance ? ` · credits ${credits.balance}` : ''}
        </p>
      </div>
      <div className="space-y-2">
        {limits.map((limit, index) => (
          <UsageLimitRows key={`${limit.limit_id || 'usage'}-${index}`} limit={limit} />
        ))}
      </div>
      {primary?.rate_limit_reached_type && (
        <p className="text-xs font-medium text-(--color-error)">
          Limit reached: {primary.rate_limit_reached_type.replaceAll('_', ' ')}
        </p>
      )}
    </div>
  )
}

// ─── ProviderCard ────────────────────────────────────────────────────────────

function ProviderCard({ provider }: { provider: ProviderInfo }) {
  const [expanded, setExpanded] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [cloudValues, setCloudValues] = useState<Record<string, string>>({})
  const [verifiedKey, setVerifiedKey] = useState('')
  const [verifiedCloudSignature, setVerifiedCloudSignature] = useState('')
  const [hasReachabilityFailure, setHasReachabilityFailure] = useState(false)
  const [oauthOpen, setOauthOpen] = useState(false)
  const [modelsExpanded, setModelsExpanded] = useState(false)
  const [modelSearch, setModelSearch] = useState('')
  const modelsMutation = useProviderModelsMutation()
  const saveMutation = useSaveProviderMutation()
  const deleteMutation = useDeleteProviderMutation()
  const saveVisibleModelsMutation = useSaveProviderVisibleModelsMutation()
  const push = useToastStore((s) => s.push)
  const queryClient = useQueryClient()

  const trimmedKey = apiKey.trim()
  const trimmedBaseUrl = baseUrl.trim()
  const primaryCredential = provider.credentials[0]
  const cloudExtra = useMemo<Record<string, string>>(() => {
    const out: Record<string, string> = {}
    for (const credential of provider.credentials) {
      out[credential.name] = (cloudValues[credential.name] ?? provider.saved_credentials[credential.name] ?? '').trim()
    }
    return out
  }, [cloudValues, provider.credentials, provider.saved_credentials])
  const cloudSignature = useMemo(() => JSON.stringify(cloudExtra), [cloudExtra])
  const hasCloudCandidate = Object.values(cloudExtra).some((value) => value.length > 0)
  const hasCandidateKey = trimmedKey.length > 0
  const hasVerifiedKey = verifiedKey === trimmedKey && hasCandidateKey
  const hasVerifiedCloud = verifiedCloudSignature === cloudSignature && hasCloudCandidate
  const canSave =
    ((provider.kind === 'api_key' || provider.kind === 'oauth') && hasVerifiedKey) ||
    (provider.kind === 'cloud_creds' && hasVerifiedCloud)

  const daemon = DAEMON_BASE_URL[provider.id]
  const extraForRequest = useMemo<Record<string, string> | undefined>(() => {
    if (!daemon || !trimmedBaseUrl) return undefined
    return { [daemon.var]: trimmedBaseUrl }
  }, [daemon, trimmedBaseUrl])

  // Auto-list models for already-connected providers (no new key typed).
  const autoFetchEnabled =
    provider.is_configured &&
    !hasCandidateKey &&
    !hasCloudCandidate &&
    (provider.kind === 'api_key' || provider.kind === 'oauth' || provider.kind === 'cloud_creds')

  const autoModelsQ = useQuery({
    queryKey: queryKeys.settings.providerModels(provider.id),
    queryFn: () => listProviderModels(provider.id, {}),
    enabled: autoFetchEnabled,
    staleTime: 60_000,
  })
  const usageQ = useProviderUsageQuery(
    provider.id,
    provider.kind === 'oauth' && provider.is_configured,
  )

  const models = useMemo<string[]>(
    () => autoModelsQ.data?.models ?? [],
    [autoModelsQ.data?.models],
  )

  const handleListModels = async () => {
    try {
      const listed = await modelsMutation.mutateAsync({
        providerId: provider.id,
        apiKey: trimmedKey,
        extra: provider.kind === 'cloud_creds' ? cloudExtra : extraForRequest,
      })
      queryClient.setQueryData(queryKeys.settings.providerModels(provider.id), listed)
      const reachedProvider = listed.source === 'provider' && listed.models.length > 0
      setHasReachabilityFailure(!reachedProvider)
      if (reachedProvider) {
        setVerifiedKey(trimmedKey)
        if (provider.kind === 'cloud_creds') setVerifiedCloudSignature(cloudSignature)
        setModelsExpanded(true)
        push({
          tone: 'success',
          title: 'Connection verified',
          description: `${listed.models.length} models available.`,
        })
      } else {
        push({
          tone: 'error',
          title: 'Failed',
          description: 'Provider is unreachable.',
        })
      }
    } catch (err) {
      setHasReachabilityFailure(true)
      push({
        tone: 'error',
        title: 'Could not list models',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const handleSave = async () => {
    try {
      const extraForSave =
        provider.kind === 'cloud_creds'
          ? cloudExtra
          : daemon !== undefined ? { [daemon.var]: trimmedBaseUrl } : undefined
      await saveMutation.mutateAsync({
        providerId: provider.id,
        body: { api_key: provider.kind === 'cloud_creds' ? '' : trimmedKey, extra: extraForSave },
      })
      setApiKey('')
      setVerifiedKey('')
      setVerifiedCloudSignature('')
      push({
        tone: 'success',
        title: 'Provider saved',
        description: provider.label,
      })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Could not save provider',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const handleClear = async () => {
    try {
      await deleteMutation.mutateAsync(provider.id)
      setApiKey('')
      setVerifiedKey('')
      setVerifiedCloudSignature('')
      setCloudValues({})
      setHasReachabilityFailure(false)
      push({
        tone: 'success',
        title: 'Provider cleared',
        description: provider.label,
      })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Could not clear provider',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const handleSaveVisibleModels = async (models: string[]) => {
    try {
      await saveVisibleModelsMutation.mutateAsync({ providerId: provider.id, models })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Could not save visible models',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const listing = modelsMutation.isPending || autoModelsQ.isFetching
  const isConnected = provider.is_configured || (provider.kind === 'oauth' && provider.is_saved)
  const isConfiguredButUnreachable =
    hasReachabilityFailure || (provider.kind !== 'oauth' && (provider.is_reachable === false || (provider.is_saved && !provider.is_configured)))

  // ── Compact card (collapsed) ────────────────────────────────────────────
  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className={cn(
          'group relative flex w-full items-center gap-3.5 rounded-lg border bg-(--bg-card) px-4 py-3.5 text-left transition-colors',
          'hover:border-(--color-border-strong)',
          'focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40',
          isConfiguredButUnreachable
            ? 'border-(--color-error)/30 hover:border-(--color-error)/40'
            : isConnected
              ? 'border-(--color-success)/25 hover:border-(--color-success)/35'
              : 'border-(--color-border)',
        )}
      >
        <ProviderBrandIcon provider={provider} size="md" />

        <div className="min-w-0 flex-1 pl-0.5">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-(--color-text)">{provider.label}</span>
            <span className="shrink-0 rounded-md bg-(--bg-key) px-1.5 py-0.5 font-mono text-[0.6rem] font-medium uppercase tracking-wider text-(--color-text-muted) ring-1 ring-(--color-border)">
              {providerKindLabel(provider.kind)}
            </span>
          </div>
          <p className="mt-0.5 line-clamp-1 text-xs text-(--color-text-muted)">{provider.description}</p>
        </div>

        <div className="flex shrink-0 items-center gap-2.5">
          {/* Status badge */}
          {isConfiguredButUnreachable && (
            <span className="inline-flex items-center gap-1 rounded-md bg-(--color-error-subtle) px-2 py-1 text-[0.65rem] font-medium text-(--color-error)">
              <AlertCircle size={11} aria-hidden="true" />
              Failed
            </span>
          )}
          {isConnected && !isConfiguredButUnreachable && (
            <span className="inline-flex items-center gap-1 rounded-md bg-(--color-success-subtle) px-2 py-1 text-[0.65rem] font-medium text-(--color-success)">
              <CheckCircle2 size={11} aria-hidden="true" />
              Connected
            </span>
          )}

          {/* Model count */}
          {models.length > 0 && (
            <span className="rounded-full bg-(--bg-key) px-2.5 py-1 font-mono text-[0.65rem] text-(--color-text-muted) ring-1 ring-(--color-border)">
              {models.length} models
            </span>
          )}

          {/* Docs link */}
          {provider.docs_url && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => { e.stopPropagation(); void openExternalUrl(provider.docs_url) }}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); void openExternalUrl(provider.docs_url) } }}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) opacity-0 transition-opacity hover:bg-(--bg-key) hover:text-(--color-text) group-hover:opacity-100"
              aria-label={`${provider.label} documentation`}
            >
              <ExternalLink size={13} aria-hidden="true" />
            </span>
          )}

          {/* Expand arrow */}
          <ChevronRight size={14} className="shrink-0 text-(--color-text-muted) transition-transform duration-(--motion-fast) group-hover:translate-x-0.5 group-hover:text-(--color-text)" aria-hidden="true" />
        </div>
      </button>
    )
  }

  // ── Expanded card ──────────────────────────────────────────────────────
  return (
    <>
      <div className={cn(
        'overflow-hidden rounded-lg border bg-(--bg-card)',
        isConfiguredButUnreachable
          ? 'border-(--color-error)/30'
          : isConnected
            ? 'border-(--color-success)/25'
            : 'border-(--color-border)',
      )}>
        <div className="space-y-4 p-4">
          {/* ── Header ──────────────────────────────────────────────────────── */}
          <div className="flex items-start gap-3">
            <ProviderBrandIcon provider={provider} size="lg" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-base font-semibold text-(--color-text)">{provider.label}</p>
                <span className="rounded-md bg-(--bg-key) px-1.5 py-0.5 font-mono text-[0.6rem] font-medium uppercase tracking-wider text-(--color-text-muted) ring-1 ring-(--color-border)">
                  {providerKindLabel(provider.kind)}
                </span>
                {isConfiguredButUnreachable ? (
                  <span className="inline-flex items-center gap-1 rounded-md bg-(--color-error-subtle) px-2 py-0.5 text-[0.65rem] font-medium text-(--color-error)">
                    <AlertCircle size={11} aria-hidden="true" />
                    Failed
                  </span>
                ) : isConnected ? (
                  <span className="inline-flex items-center gap-1 rounded-md bg-(--color-success-subtle) px-2 py-0.5 text-[0.65rem] font-medium text-(--color-success)">
                    <CheckCircle2 size={11} aria-hidden="true" />
                    Connected
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-(--color-text-muted)">{provider.description}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {provider.docs_url && (
                <Button type="button" size="icon-xs" variant="ghost" onClick={() => void openExternalUrl(provider.docs_url)} aria-label="Open documentation">
                  <ExternalLink size={13} aria-hidden="true" />
                </Button>
              )}
              <Button type="button" size="icon-xs" variant="ghost" onClick={() => setExpanded(false)} aria-label="Collapse">
                <ChevronDown size={13} aria-hidden="true" />
              </Button>
            </div>
          </div>

          {/* ── Configuration section ───────────────────────────────────────── */}
          <div className="rounded-lg border border-(--color-border-subtle) bg-(--bg-page)/50 p-4">
            <div className="mb-3 flex items-center gap-2">
              <KeyRound size={13} className="text-(--color-text-muted)" aria-hidden="true" />
              <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-(--color-text-muted)">Configuration</p>
            </div>

            {/* ── API-key controls ────────────────────────────────────────────── */}
            {provider.kind === 'api_key' && (
              <div className="space-y-3">
                <label className="block">
                  <span className="text-xs font-medium text-(--color-text-muted)">{primaryCredential?.label || 'API key'}</span>
                  <div className="relative mt-1.5">
                    <Input
                      type="password"
                      value={apiKey}
                      onChange={(event) => {
                        setApiKey(event.target.value)
                        setVerifiedKey('')
                      }}
                      placeholder={primaryCredential?.placeholder || (provider.is_configured ? 'Enter a new key to replace current key' : 'Paste your API key')}
                      autoComplete="off"
                      className="h-10 font-mono text-xs pr-10"
                    />
                    {trimmedKey && (
                      <div className="absolute right-2 top-1/2 -translate-y-1/2">
                        {hasVerifiedKey ? (
                          <CheckCircle2 size={14} className="text-(--color-success)" aria-label="Key verified" />
                        ) : (
                          <AlertCircle size={14} className="text-(--color-text-muted)" aria-label="Key not yet verified" />
                        )}
                      </div>
                    )}
                  </div>
                </label>
                {daemon && (
                  <label className="block">
                    <span className="text-xs font-medium text-(--color-text-muted)">Base URL <span className="text-(--color-text-muted)/60">(optional)</span></span>
                    <Input
                      type="url"
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                      placeholder={daemon.placeholder}
                      autoComplete="off"
                      className="mt-1.5 h-10 font-mono text-xs"
                      spellCheck={false}
                    />
                  </label>
                )}
                <div className="flex items-center gap-2 pt-1">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={handleListModels}
                    disabled={!hasCandidateKey || listing}
                  >
                    {listing && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                    List models
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={handleSave}
                    disabled={!canSave || saveMutation.isPending}
                  >
                    {saveMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                    Save
                  </Button>
                  {provider.is_configured && (
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      onClick={handleClear}
                      disabled={saveMutation.isPending}
                    >
                      Clear
                    </Button>
                  )}
                </div>
                {hasCandidateKey && !hasVerifiedKey && (
                  <p className="text-xs text-(--color-text-muted)">
                    Click <span className="font-medium text-(--color-text)">List models</span> to verify this key before saving.
                  </p>
                )}
                {!hasCandidateKey && provider.is_configured && (
                  <p className="text-xs text-(--color-text-muted)">
                    Key saved. Type a new one above to replace, or click <span className="font-medium text-(--color-text)">Clear</span> to remove.
                  </p>
                )}
              </div>
            )}

            {/* ── OAuth providers ─────────────────────────────────────────────── */}
            {provider.kind === 'oauth' && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Button type="button" size="sm" onClick={() => setOauthOpen(true)}>
                    <ShieldCheck size={14} aria-hidden="true" />
                    {provider.is_configured ? 'Re-authenticate' : 'Connect'}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={handleListModels}
                    disabled={!provider.is_configured || listing}
                  >
                    {listing && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                    List models
                  </Button>
                  {provider.is_configured && (
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      onClick={handleClear}
                      disabled={deleteMutation.isPending}
                    >
                      Disconnect
                    </Button>
                  )}
                </div>
                {provider.is_configured ? (
                  <p className="text-xs text-(--color-text-muted)">
                    Connected via OAuth. Click <span className="font-medium text-(--color-text)">Re-authenticate</span> to refresh your token, or <span className="font-medium text-(--color-text)">List models</span> to update the catalog.
                  </p>
                ) : (
                  <p className="text-xs text-(--color-text-muted)">
                    Authenticate with your {provider.label} account to access available models.
                  </p>
                )}
              </div>
            )}

            {/* ── Local daemon (Ollama) — optional base URL only ──────────────── */}
            {provider.kind === 'local' && daemon && (
              <div className="space-y-3">
                <label className="block">
                  <span className="text-xs font-medium text-(--color-text-muted)">Base URL</span>
                  <Input
                    type="url"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder={daemon.placeholder}
                    autoComplete="off"
                    className="mt-1.5 h-10 font-mono text-xs"
                    spellCheck={false}
                  />
                </label>
                <div className="flex items-center gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={handleListModels} disabled={listing}>
                    {listing && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                    List models
                  </Button>
                  <Button type="button" size="sm" onClick={handleSave} disabled={saveMutation.isPending}>
                    {saveMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                    Save
                  </Button>
                </div>
                <p className="text-xs text-(--color-text-muted)">
                  Leave blank to use the default at <span className="font-mono text-(--color-text)">{daemon.placeholder}</span>
                </p>
              </div>
            )}

            {/* ── Cloud credential providers (Bedrock, Vertex AI) ──────────────── */}
            {provider.kind === 'cloud_creds' && (
              <div className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  {provider.credentials.map((credential) => (
                    <label key={credential.name} className="block">
                      <span className="text-xs font-medium text-(--color-text-muted)">{credential.label}</span>
                      <Input
                        type={credential.secret ? 'password' : 'text'}
                        value={cloudValues[credential.name] ?? provider.saved_credentials[credential.name] ?? ''}
                        onChange={(e) => {
                          setCloudValues((values) => ({ ...values, [credential.name]: e.target.value }))
                          setVerifiedCloudSignature('')
                        }}
                        placeholder={credential.placeholder}
                        autoComplete="off"
                        className="mt-1.5 h-10 font-mono text-xs"
                        spellCheck={false}
                      />
                    </label>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={handleListModels} disabled={!hasCloudCandidate || listing}>
                    {listing && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                    List models
                  </Button>
                  <Button type="button" size="sm" onClick={handleSave} disabled={!canSave || saveMutation.isPending}>
                    {saveMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                    Save
                  </Button>
                  {provider.is_configured && (
                    <Button type="button" size="sm" variant="destructive" onClick={handleClear} disabled={deleteMutation.isPending}>
                      Clear
                    </Button>
                  )}
                </div>
                {hasCloudCandidate && !hasVerifiedCloud && (
                  <p className="text-xs text-(--color-text-muted)">
                    Click <span className="font-medium">List models</span> to verify these credentials before saving.
                  </p>
                )}
                {!hasCloudCandidate && provider.is_configured && (
                  <p className="text-xs text-(--color-text-muted)">
                    Credentials saved. Type new values above only if you want to replace them.
                  </p>
                )}
              </div>
            )}

            {/* ── Detected providers (local without base URL) ────────────────── */}
            {provider.kind !== 'api_key' && provider.kind !== 'oauth' && provider.kind !== 'cloud_creds' && !daemon && (
              <p className="text-xs text-(--color-text-muted)">
                Detected from local environment or system credentials.
              </p>
            )}
          </div>

          {/* ── OAuth usage panel ───────────────────────────────────────────── */}
          {provider.kind === 'oauth' && provider.is_configured && (
            <div className="space-y-2">
              {usageQ.isLoading ? (
                <p className="inline-flex items-center gap-1 text-xs text-(--color-text-muted)">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  Loading active usage…
                </p>
              ) : usageQ.data ? (
                <UsagePanel limits={usageQ.data.limits} />
              ) : usageQ.isError ? (
                <p className="text-xs text-(--color-text-muted)">
                  {usageQ.error instanceof ApiValidationError && usageQ.error.status === 404
                    ? 'Usage monitoring is not supported for this OAuth provider yet.'
                    : 'Usage monitor unavailable right now.'}
                </p>
              ) : null}
            </div>
          )}

          {/* ── Models panel ──────────────────────────────────────────────────── */}
          {models.length > 0 && (
            <ModelsPanel
              providerId={provider.id}
              models={models}
              visibleModels={provider.visible_models}
              search={modelSearch}
              onSearchChange={setModelSearch}
              expanded={modelsExpanded}
              onToggle={() => setModelsExpanded((v) => !v)}
              onSaveVisibleModels={handleSaveVisibleModels}
              savingVisibleModels={saveVisibleModelsMutation.isPending}
            />
          )}
        </div>
      </div>

      {provider.kind === 'oauth' && oauthOpen && (
        <OAuthLoginDialog provider={provider} open={oauthOpen} onOpenChange={setOauthOpen} />
      )}
    </>
  )
}

// ─── Models panel ────────────────────────────────────────────────────────────

type IndexedModel = {
  modelId: string
  qualifiedId: string
}

function ModelsPanel({
  providerId,
  models,
  visibleModels,
  search,
  onSearchChange,
  expanded,
  onToggle,
  onSaveVisibleModels,
  savingVisibleModels,
}: {
  providerId: string
  models: string[]
  visibleModels: string[]
  search: string
  onSearchChange: (v: string) => void
  expanded: boolean
  onToggle: () => void
  onSaveVisibleModels: (models: string[]) => Promise<void>
  savingVisibleModels: boolean
}) {
  const push = useToastStore((s) => s.push)
  const visibleSet = useMemo(() => new Set(visibleModels), [visibleModels])
  const allVisible = visibleSet.size === 0

  const handleCopy = async (qualifiedId: string) => {
    try {
      await navigator.clipboard.writeText(qualifiedId)
      push({ tone: 'success', title: 'Copied', description: qualifiedId })
    } catch {
      push({ tone: 'error', title: 'Copy failed', description: qualifiedId })
    }
  }

  const indexed = useMemo<IndexedModel[]>(
    () => models.map((id) => ({ modelId: id, qualifiedId: `${providerId}:${id}` })),
    [providerId, models],
  )

  const visible = useMemo<IndexedModel[]>(() => {
    const q = search.trim()
    if (!q) return indexed
    const results = fuzzysort.go(q, indexed, {
      key: 'qualifiedId',
      threshold: 0.2,
      limit: 200,
    })
    return results.map((r) => r.obj)
  }, [indexed, search])
  const visibleCount = allVisible ? indexed.length : visibleSet.size

  const toggleVisibleModel = (modelId: string) => {
    const next = new Set(visibleModels)
    if (next.has(modelId)) next.delete(modelId)
    else next.add(modelId)
    void onSaveVisibleModels(Array.from(next).sort())
  }

  const showAll = () => {
    void onSaveVisibleModels([])
  }

  return (
    <div className="overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-page)/50">
      <button
        type="button"
        onClick={onToggle}
        className="flex min-h-12 w-full items-center justify-between gap-2 px-4 py-3 text-left transition-colors hover:bg-(--bg-key)/50 md:min-h-0"
        aria-expanded={expanded}
      >
        <span className="flex items-center gap-2.5">
          <span className="text-sm font-semibold text-(--color-text)">Models</span>
          <span className="rounded-full bg-(--color-accent-subtle) px-2 py-0.5 font-mono text-[0.65rem] tabular-nums text-(--color-text-muted)">
            {indexed.length}
          </span>
          {!allVisible && (
            <span className="rounded-full bg-(--color-success-subtle) px-2 py-0.5 text-[0.65rem] font-medium text-(--color-success)">
              {visibleCount} visible
            </span>
          )}
          {allVisible && indexed.length > 0 && (
            <span className="text-[0.65rem] text-(--color-text-muted)">all visible</span>
          )}
        </span>
        <ChevronDown
          size={14}
          className={cn('shrink-0 text-(--color-text-muted) transition-transform duration-(--motion-fast)', expanded && 'rotate-180')}
          aria-hidden="true"
        />
      </button>
      {expanded && (
        <div className="border-t border-(--color-border-subtle) p-4">
          <div className="relative">
            <Search size={13} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-(--color-text-muted)" aria-hidden="true" />
            <Input
              type="search"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search models…"
              className="h-9 pl-9 text-xs"
              aria-label="Filter models"
            />
          </div>
          <div className="mt-3 flex items-center justify-between">
            <p className="text-[0.65rem] text-(--color-text-muted)">
              Toggle visibility to control which models appear in EvoFlux pickers.
            </p>
            {!allVisible && (
              <button
                type="button"
                onClick={showAll}
                className="text-[0.65rem] font-medium text-(--color-accent) hover:text-(--color-accent-foreground)"
              >
                Show all
              </button>
            )}
          </div>
          <ul className="mt-3 max-h-72 divide-y divide-(--color-border-subtle) overflow-y-auto rounded-lg border border-(--color-border-subtle) bg-(--bg-card)/50">
            {visible.length === 0 ? (
              <li className="px-4 py-6 text-center text-xs text-(--color-text-muted)">No matching models</li>
            ) : (
              visible.map(({ qualifiedId, modelId }) => (
                <ModelRow
                  key={qualifiedId}
                  qualifiedId={qualifiedId}
                  selected={!allVisible && visibleSet.has(modelId)}
                  savingVisibleModels={savingVisibleModels}
                  onToggleVisible={() => toggleVisibleModel(modelId)}
                  onCopy={handleCopy}
                />
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  )
}

// ─── Model row ───────────────────────────────────────────────────────────────

function ModelRow({
  qualifiedId,
  selected,
  savingVisibleModels,
  onToggleVisible,
  onCopy,
}: {
  qualifiedId: string
  selected: boolean
  savingVisibleModels: boolean
  onToggleVisible: () => void
  onCopy: (qualifiedId: string) => Promise<void>
}) {
  const isMobile = useIsMobile()
  const { isTauri, os } = usePlatform()
  const isTauriMobile = isTauri && (os === 'ios' || os === 'android')
  const [actionsPoint, setActionsPoint] = useState<{ x: number; y: number } | null>(null)
  const longPressTimerRef = useRef<number | null>(null)
  const longPressStartRef = useRef<{ x: number; y: number } | null>(null)

  const clearLongPress = () => {
    if (longPressTimerRef.current !== null) window.clearTimeout(longPressTimerRef.current)
    longPressTimerRef.current = null
    longPressStartRef.current = null
  }

  return (
    <li
      className={cn(
        'flex min-h-11 items-center gap-2 px-3 py-2 transition-colors md:min-h-0',
        selected ? 'bg-(--color-success-subtle)/30' : 'hover:bg-(--bg-key)/50',
      )}
      onContextMenu={(event) => {
        if (isTauriMobile) return
        event.preventDefault()
        setActionsPoint({ x: event.clientX, y: event.clientY })
      }}
      onPointerDown={(event) => {
        if (!isMobile || !isTauriMobile || event.pointerType === 'mouse') return
        longPressStartRef.current = { x: event.clientX, y: event.clientY }
        longPressTimerRef.current = window.setTimeout(() => {
          longPressTimerRef.current = null
          longPressStartRef.current = null
          mediumHapticFeedback()
          setActionsPoint({ x: event.clientX, y: event.clientY })
        }, MODEL_LONG_PRESS_MS)
      }}
      onPointerMove={(event) => {
        const start = longPressStartRef.current
        if (!start) return
        if (
          Math.abs(event.clientX - start.x) > MODEL_LONG_PRESS_MOVE_TOLERANCE ||
          Math.abs(event.clientY - start.y) > MODEL_LONG_PRESS_MOVE_TOLERANCE
        ) {
          clearLongPress()
        }
      }}
      onPointerUp={clearLongPress}
      onPointerCancel={clearLongPress}
      onPointerLeave={clearLongPress}
    >
      <span className="min-w-0 flex-1 truncate font-mono text-xs text-(--color-text)">
        {qualifiedId}
      </span>
      <button
        type="button"
        onClick={onToggleVisible}
        disabled={savingVisibleModels}
        className={cn(
          'flex h-7 min-w-[5rem] items-center justify-center gap-1.5 rounded-lg px-2.5 text-[0.7rem] font-medium transition-colors md:h-6',
          selected
            ? 'bg-(--color-success) text-white'
            : 'border border-(--color-border) text-(--color-text-muted) hover:border-(--color-border-strong) hover:bg-(--bg-card) hover:text-(--color-text)',
        )}
        aria-label={`${selected ? 'Remove' : 'Show'} ${qualifiedId} in model pickers`}
        title={selected ? 'Remove from visible models' : 'Show in pickers'}
      >
        {savingVisibleModels ? <Loader2 size={11} className="animate-spin" aria-hidden="true" /> : selected ? <Check size={11} aria-hidden="true" /> : null}
        {selected ? 'Visible' : 'Show'}
      </button>
      <button
        type="button"
        onClick={() => void onCopy(qualifiedId)}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) transition-colors hover:bg-(--bg-card) hover:text-(--color-text) md:h-6 md:w-6"
        aria-label={`Copy ${qualifiedId}`}
      >
        <Copy size={12} aria-hidden="true" />
      </button>
      {actionsPoint && (
        <div
          className="fixed inset-0 z-(--z-lightbox)"
          onClick={() => setActionsPoint(null)}
          onContextMenu={(event) => {
            event.preventDefault()
            setActionsPoint(null)
          }}
        >
          <div
            role="menu"
            aria-label={`Actions for ${qualifiedId}`}
            className="fixed min-w-48 rounded-xl border border-(--color-border) bg-(--bg-card) p-1.5 text-sm text-(--color-text) shadow-xl"
            style={{ left: actionsPoint.x, top: actionsPoint.y }}
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
              onClick={() => {
                setActionsPoint(null)
                void onCopy(qualifiedId)
              }}
            >
              <Copy size={14} aria-hidden="true" />
              Copy model ID
            </button>
          </div>
        </div>
      )}
    </li>
  )
}

// ─── OAuth login dialog ──────────────────────────────────────────────────────

function OAuthLoginDialog({
  provider,
  open,
  onOpenChange,
}: {
  provider: ProviderInfo
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [events, setEvents] = useState<OAuthLoginEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [codeCopied, setCodeCopied] = useState(false)
  const [authMode, setAuthMode] = useState<'device' | 'browser'>('device')
  const [submittingCode, setSubmittingCode] = useState(false)
  const openedUrlRef = useRef<string | null>(null)
  const successHandledRef = useRef(false)
  const queryClient = useQueryClient()
  const latest = events.at(-1)
  const deviceEvent = events.find((event) => event.event === 'device_code')
  const isSuccess = latest?.event === 'success'
  const isWorking = open && !isSuccess && !error

  const copyDeviceCode = async () => {
    if (!deviceEvent?.user_code) return
    try {
      await navigator.clipboard.writeText(deviceEvent.user_code)
      setCodeCopied(true)
      window.setTimeout(() => setCodeCopied(false), 1500)
    } catch {
      // Copy is best-effort; the code remains visible for manual entry.
    }
  }

  useEffect(() => {
    if (!open) return undefined
    const abort = new AbortController()
    openedUrlRef.current = null
    successHandledRef.current = false
    oauthLoginStream(
      provider.id,
      {
        onEvent: () => undefined,
        onOAuthEvent: (event) => {
          setEvents((current) => [...current, event])
          if (event.verification_uri && openedUrlRef.current !== event.verification_uri) {
            openedUrlRef.current = event.verification_uri
            void openExternalUrl(event.verification_uri)
          }
          if (event.event === 'success' && !successHandledRef.current) {
            successHandledRef.current = true
            void queryClient.invalidateQueries({ queryKey: queryKeys.settings.providers() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.agentFiles.registry() })
            const model = event.suggested_model
            if (model) {
              void installSeed(model)
                .then(() => {
                  useToastStore.getState().push({
                    tone: 'success',
                    title: 'Provider connected',
                    description: 'Default agents and skills are ready.',
                  })
                })
                .catch((err: unknown) => {
                  useToastStore.getState().push({
                    tone: 'error',
                    title: 'Seed install failed',
                    description: err instanceof Error ? err.message : String(err),
                  })
                })
            } else {
              useToastStore.getState().push({ tone: 'success', title: 'Provider connected', description: provider.label })
            }
          }
          if (event.event === 'failed') {
            setError(event.message ?? 'OAuth login failed')
          }
        },
        onError: (err) => {
          if (successHandledRef.current && isBenignOAuthStreamClose(err.message)) return
          setError(err.message)
        },
      },
      abort.signal,
      authMode === 'browser' ? 'browser' : undefined,
    )
    return () => abort.abort()
  }, [authMode, open, provider.id, provider.label, queryClient])

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) setAuthMode('device')
        onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Connect {provider.label}</DialogTitle>
          <DialogDescription>Approve the browser prompt. This window will update when the token is saved.</DialogDescription>
        </DialogHeader>
        <div className="min-w-0 space-y-4">
          {/* Status indicator */}
          <div className={cn(
            'flex items-center gap-3 rounded-xl p-4 transition-colors',
            isSuccess
              ? 'border border-(--color-success)/30 bg-(--color-success-subtle)'
              : error
                ? 'border border-(--color-error)/30 bg-(--color-error)/10'
                : 'border border-(--color-border) bg-(--bg-key)',
          )}>
            <div className={cn(
              'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
              isSuccess
                ? 'bg-(--color-success) text-white'
                : error
                  ? 'bg-(--color-error) text-white'
                  : 'bg-(--bg-card) text-(--color-accent) ring-1 ring-(--color-border)',
            )}>
              {isWorking ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" /> : <CheckCircle2 className="h-5 w-5" aria-hidden="true" />}
            </div>
            <div>
              <p className="text-sm font-medium text-(--color-text)">{latest ? eventLabel(latest) : 'Starting secure login'}</p>
              <p className="mt-0.5 text-xs text-(--color-text-muted)">Keep this dialog open until setup completes.</p>
            </div>
          </div>

          {/* Device code section */}
          {deviceEvent?.user_code && (
            <div className="overflow-hidden rounded-xl border border-(--accent-blue)/25 bg-(--accent-blue-soft)">
              <div className="p-6 text-center">
                <p className="text-[0.65rem] font-semibold tracking-[0.2em] text-(--color-text-muted) uppercase">Device code</p>
                <div className="mt-3 flex flex-col items-center justify-center gap-3 sm:flex-row">
                  <p className="font-mono text-4xl font-bold tracking-[0.15em] text-(--color-text)">{deviceEvent.user_code}</p>
                  <button
                    type="button"
                    onClick={() => { void copyDeviceCode() }}
                    className={cn(
                      'flex h-10 w-10 items-center justify-center rounded-lg border transition-all',
                      codeCopied
                        ? 'border-(--color-success)/30 bg-(--color-success-subtle) text-(--color-success)'
                        : 'border-(--color-border) bg-(--bg-card) text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                    )}
                    aria-label="Copy device code"
                    title="Copy device code"
                  >
                    {codeCopied ? <Check size={16} /> : <Copy size={16} />}
                  </button>
                </div>
                <p className="mx-auto mt-3 max-w-sm text-xs leading-relaxed text-(--color-text-muted)">
                  {deviceCodeHelp(provider.id)}
                </p>
                {deviceEvent.verification_uri && (
                  <Button className="mt-4 min-h-11 w-full sm:min-h-0" size="default" onClick={() => void openExternalUrl(deviceEvent.verification_uri!)}>
                    Open authorization page
                  </Button>
                )}
              </div>
              {provider.id === 'codex' && authMode !== 'browser' && !isSuccess && (
                <div className="border-t border-(--accent-blue)/20 bg-(--bg-page)/70 p-4 text-left">
                  <p className="text-xs font-medium text-(--color-text)">Workspace account?</p>
                  <p className="mt-1 text-xs leading-relaxed text-(--color-text-muted)">
                    If the Codex page says your admin must enable device-code authentication, switch to browser sign-in.
                  </p>
                  <Button
                    className="mt-3 min-h-11 w-full sm:min-h-0"
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setError(null)
                      setEvents([])
                      setAuthMode('browser')
                    }}
                  >
                    Use browser sign-in instead
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* Code required form */}
          {latest?.event === 'code_required' && (
            <form
              className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-page) p-4"
              onSubmit={(event) => {
                event.preventDefault()
                setSubmittingCode(true)
                submitOAuthCallback(provider.id, code)
                  .then((result) => {
                    setEvents((current) => [...current, { event: 'success', suggested_model: result.suggested_model }])
                    void queryClient.invalidateQueries({ queryKey: queryKeys.settings.providers() })
                    void queryClient.invalidateQueries({ queryKey: queryKeys.agentFiles.registry() })

                    useToastStore.getState().push({ tone: 'success', title: 'Provider connected', description: provider.label })
                  })
                  .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
                  .finally(() => setSubmittingCode(false))
              }}
            >
              <label className="block text-xs font-medium text-(--color-text-muted)">
                Paste authorization callback URL/code
                <Input value={code} onChange={(event) => setCode(event.target.value)} className="mt-1.5" autoComplete="off" />
              </label>
              <Button type="submit" size="sm" disabled={!code.trim() || submittingCode}>
                {submittingCode && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                Finish connection
              </Button>
            </form>
          )}

          {/* Success message */}
          {isSuccess && (
            <div className="flex items-center gap-2 rounded-xl bg-(--color-success-subtle) p-4">
              <CheckCircle2 size={16} className="shrink-0 text-(--color-success)" aria-hidden="true" />
              <p className="text-sm font-medium text-(--color-success)">Connected successfully</p>
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="flex items-start gap-2 rounded-xl bg-(--color-error)/10 p-4">
              <AlertCircle size={16} className="mt-0.5 shrink-0 text-(--color-error)" aria-hidden="true" />
              <p className="text-sm text-(--color-error)">{error}</p>
            </div>
          )}

          {/* Technical details */}
          {events.length > 0 && (
            <details className="overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-page)">
              <summary className="flex cursor-pointer items-center gap-2 px-4 py-3 text-xs font-medium text-(--color-text-muted) hover:text-(--color-text)">
                <TerminalSquare size={13} aria-hidden="true" />
                Technical details
              </summary>
              <div className="max-h-40 overflow-auto border-t border-(--color-border-subtle) p-4 space-y-2">
                {events.map((event, index) => (
                  <p key={`${event.event}-${index}`} className="min-w-0 text-xs text-(--color-text-muted) [overflow-wrap:anywhere]">
                    <span className="font-mono text-(--color-text)">{event.event}</span>
                    {event.message ? ` · ${event.message}` : ''}
                  </p>
                ))}
              </div>
            </details>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ─── Main page ───────────────────────────────────────────────────────────────

export function ProvidersSettingsPage() {
  const providersQ = useProvidersQuery()
  const [search, setSearch] = useState('')

  const providers = providersQ.data?.providers ?? []
  const connectedProviders = providers.filter((p) => p.is_configured || (p.kind === 'oauth' && p.is_saved))
  const availableProviders = providers.filter((p) => !p.is_configured && !(p.kind === 'oauth' && p.is_saved))

  const filteredConnected = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return connectedProviders
    return connectedProviders.filter(
      (p) => p.label.toLowerCase().includes(q) || p.description.toLowerCase().includes(q) || p.id.toLowerCase().includes(q),
    )
  }, [connectedProviders, search])

  const filteredAvailable = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return availableProviders
    return availableProviders.filter(
      (p) => p.label.toLowerCase().includes(q) || p.description.toLowerCase().includes(q) || p.id.toLowerCase().includes(q),
    )
  }, [availableProviders, search])

  const totalFiltered = filteredConnected.length + filteredAvailable.length

  return (
    <SettingsPage
      icon={KeyRound}
      title="Providers"
      lede="Connect a model provider so EvoFlux can run agents. API keys and OAuth tokens are stored on this machine only."
      actions={
        connectedProviders.length > 0 ? (
          <span className="rounded-full bg-(--color-success-subtle) px-2.5 py-1 text-[11px] font-medium text-(--color-success)">
            {connectedProviders.length} connected
          </span>
        ) : undefined
      }
    >
      {!providersQ.isLoading && providers.length > 0 && (
        <div className="flex h-10 items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-card) px-3 focus-within:border-(--focus-ring) focus-within:ring-3 focus-within:ring-(--focus-ring)/30">
          <Search size={14} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search providers…"
            aria-label="Search providers"
            className="h-full flex-1 border-0 bg-transparent px-0 text-sm shadow-none focus:ring-0 focus-visible:ring-0"
          />
          <span className="shrink-0 font-mono text-xs tabular-nums text-(--color-text-muted)">
            {totalFiltered} {totalFiltered === 1 ? 'provider' : 'providers'}
          </span>
        </div>
      )}

      {providersQ.isLoading && (
        <div className="flex items-center gap-2 py-12 text-sm text-(--color-text-muted)">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          Loading providers…
        </div>
      )}

      {providersQ.error && (
        <SettingsCallout tone="error" icon={AlertCircle}>
          <p className="font-medium">Failed to load providers</p>
          <p className="mt-1 text-(--color-text-muted)">
            {providersQ.error instanceof Error ? providersQ.error.message : String(providersQ.error)}
          </p>
        </SettingsCallout>
      )}

      {!providersQ.isLoading && !providersQ.error && (
        <>
          {filteredConnected.length > 0 && (
            <SettingsGroup title="Connected" bare className="space-y-2">
              {filteredConnected.map((provider) => (
                <ProviderCard key={provider.id} provider={provider} />
              ))}
            </SettingsGroup>
          )}

          {filteredAvailable.length > 0 && (
            <SettingsGroup
              title="Available"
              description="Add a key or sign in to make these usable by your agents."
              bare
              className="space-y-2"
            >
              {filteredAvailable.map((provider) => (
                <ProviderCard key={provider.id} provider={provider} />
              ))}
            </SettingsGroup>
          )}

          {totalFiltered === 0 && search.trim() && (
            <div className="rounded-lg border border-dashed border-(--color-border) py-12 text-center">
              <p className="text-sm text-(--color-text-muted)">
                No providers match &ldquo;{search}&rdquo;.
              </p>
              <button
                type="button"
                onClick={() => setSearch('')}
                className="mt-2 text-sm font-medium text-(--color-text) underline-offset-2 hover:underline"
              >
                Clear search
              </button>
            </div>
          )}

          {providers.length === 0 && (
            <div className="rounded-lg border border-dashed border-(--color-border) py-12 text-center">
              <p className="text-sm font-medium text-(--color-text)">No providers available</p>
              <p className="mt-1 text-xs text-(--color-text-muted)">
                Check the backend connection and try again.
              </p>
            </div>
          )}
        </>
      )}
    </SettingsPage>
  )
}
