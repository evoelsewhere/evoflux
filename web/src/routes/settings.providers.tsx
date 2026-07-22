import { useEffect, useMemo, useRef, useState } from 'react'
import fuzzysort from 'fuzzysort'
import {
  AlertCircle,
  ArrowLeft,
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
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
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
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { usePlatform } from '@/hooks/use-platform'
import { mediumHapticFeedback } from '@/lib/haptics'
import { useToastStore } from '@/stores/useToastStore'
import { isTransientNetworkError } from '@/utils/errors'
import { cn } from '@/lib/utils'

// ─── Constants ──────────────────────────────────────────────────────────────

const MODEL_LONG_PRESS_MS = 520
const MODEL_LONG_PRESS_MOVE_TOLERANCE = 10

// ─── Provider brand identity ────────────────────────────────────────────────

interface ProviderBrand {
  /** CSS class string for the brand icon background + text color. */
  iconClass: string
  /** Tagline or short descriptor for the provider. */
  tagline?: string
}

const PROVIDER_BRANDS: Record<string, ProviderBrand> = {
  anthropic: { iconClass: 'bg-[#D4A574]/15 text-[#D4A574] ring-[#D4A574]/20', tagline: 'Claude models' },
  openai: { iconClass: 'bg-[#10A37F]/15 text-[#10A37F] ring-[#10A37F]/20', tagline: 'GPT & reasoning' },
  copilot: { iconClass: 'bg-[#6E40C9]/15 text-[#6E40C9] ring-[#6E40C9]/20', tagline: 'GitHub Copilot' },
  codex: { iconClass: 'bg-[#10A37F]/15 text-[#10A37F] ring-[#10A37F]/20', tagline: 'Codex CLI' },
  ollama: { iconClass: 'bg-white/10 text-white/80 ring-white/15', tagline: 'Local inference' },
  router9: { iconClass: 'bg-[#60A5FA]/15 text-[#60A5FA] ring-[#60A5FA]/20', tagline: 'Model router' },
  cliproxy: { iconClass: 'bg-[#F59E0B]/15 text-[#F59E0B] ring-[#F59E0B]/20', tagline: 'CLI proxy' },
  xiaomi: { iconClass: 'bg-[#FF6900]/15 text-[#FF6900] ring-[#FF6900]/20', tagline: 'MiLM models' },
  kimi: { iconClass: 'bg-[#7C3AED]/15 text-[#7C3AED] ring-[#7C3AED]/20', tagline: 'Moonshot AI' },
  foundry: { iconClass: 'bg-[#0078D4]/15 text-[#0078D4] ring-[#0078D4]/20', tagline: 'Azure AI Foundry' },
  fci: { iconClass: 'bg-[#F26522]/15 text-[#F26522] ring-[#F26522]/20', tagline: 'FPT inference gateway' },
}

function getProviderBrand(id: string): ProviderBrand {
  return PROVIDER_BRANDS[id] ?? { iconClass: 'bg-(--bg-key) text-(--color-text-muted) ring-(--color-border)' }
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

// ─── Brand icon ──────────────────────────────────────────────────────────────

function ProviderBrandIcon({ provider, size = 'md' }: { provider: ProviderInfo; size?: 'sm' | 'md' | 'lg' }) {
  const brand = getProviderBrand(provider.id)
  const sizeClasses = {
    sm: 'h-8 w-8',
    md: 'h-10 w-10',
    lg: 'h-12 w-12',
  }
  const svgSizes = {
    sm: 16,
    md: 20,
    lg: 24,
  }

  const renderLogo = () => {
    const s = svgSizes[size]
    switch (provider.id) {
      case 'anthropic':
        return (
          <svg width={s} height={s} viewBox="0 0 256 176" fill="currentColor">
            <path d="M147.487 0C147.487 0 217.568 175.78 217.568 175.78H256L185.919 0H147.487ZM70.071 0C70.071 0 0 175.78 0 175.78H39.179L53.51 138.866H126.818L141.146 175.78H180.325L110.254 0H70.071ZM66.183 106.221L90.162 44.447L114.142 106.221H66.183Z"/>
          </svg>
        )
      case 'openai':
        return (
          <svg width={s} height={s} viewBox="0 0 256 260" fill="currentColor">
            <path d="M239.184 106.203C245.054 88.524 243.022 69.173 233.608 53.1C219.452 28.459 191 15.784 163.213 21.74C147.554 4.321 123.795-3.424 100.879 1.419C77.963 6.261 59.369 22.957 52.096 45.221C33.844 48.964 18.09 60.393 8.867 76.582C-5.443 101.183-2.195 132.215 16.899 153.32C11.006 170.991 13.02 190.344 22.424 206.423C36.598 231.072 65.068 243.747 92.87 237.783C105.236 251.708 123.001 259.631 141.624 259.527C170.105 259.552 195.338 241.166 204.038 214.046C222.287 210.296 238.038 198.87 247.267 182.685C261.404 158.128 258.142 127.263 239.184 106.203ZM141.624 242.541C130.256 242.559 119.244 238.575 110.519 231.286L163.725 200.591C166.341 199.056 167.954 196.257 167.971 193.224V120.374L189.816 133.01C190.034 133.121 190.186 133.331 190.225 133.573V193.94C190.169 220.758 168.442 242.485 141.624 242.541ZM37.158 197.931C31.456 188.086 29.409 176.547 31.377 165.342L84.633 196.089C87.239 197.618 90.468 197.618 93.074 196.089L156.255 159.664V184.885C156.244 185.15 156.112 185.395 155.897 185.55L103.562 215.734C80.305 229.132 50.592 221.165 37.158 197.931ZM23.549 85.381C29.29 75.473 38.351 67.916 49.129 64.048V125.439C49.089 128.459 50.697 131.263 53.324 132.754L116.198 169.026L94.353 181.662C94.113 181.789 93.826 181.789 93.586 181.662L41.353 151.53C18.142 138.076 10.182 108.386 23.549 85.125V85.381ZM203.015 127.076L139.936 90.446L161.729 77.861C161.969 77.733 162.257 77.733 162.497 77.861L214.73 108.045C231.032 117.452 240.437 135.426 238.872 154.183C237.306 172.939 225.051 189.106 207.414 195.68V134.289C207.323 131.277 205.651 128.536 203.015 127.076ZM224.757 94.385L171.603 63.383C168.981 61.844 165.732 61.844 163.111 63.383L99.981 99.808V74.587C99.953 74.325 100.071 74.07 100.288 73.922L152.521 43.789C168.863 34.374 189.174 35.253 204.643 46.043C220.111 56.834 227.949 75.592 224.757 94.18V94.385ZM88.061 139.098L66.216 126.513C65.995 126.379 65.845 126.154 65.807 125.899V65.685C65.831 46.829 76.75 29.685 93.827 21.688C110.904 13.692 131.064 16.284 145.563 28.339L92.358 59.034C89.742 60.569 88.128 63.368 88.112 66.401L88.061 139.098ZM99.929 113.519L128.067 97.301L156.255 113.519V145.953L128.169 162.171L99.981 145.953L99.929 113.519Z"/>
          </svg>
        )
      case 'copilot':
        return (
          <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/>
          </svg>
        )
      case 'codex':
        return (
          <svg width={s} height={s} viewBox="0 0 256 260" fill="currentColor">
            <path d="M239.184 106.203C245.054 88.524 243.022 69.173 233.608 53.1C219.452 28.459 191 15.784 163.213 21.74C147.554 4.321 123.795-3.424 100.879 1.419C77.963 6.261 59.369 22.957 52.096 45.221C33.844 48.964 18.09 60.393 8.867 76.582C-5.443 101.183-2.195 132.215 16.899 153.32C11.006 170.991 13.02 190.344 22.424 206.423C36.598 231.072 65.068 243.747 92.87 237.783C105.236 251.708 123.001 259.631 141.624 259.527C170.105 259.552 195.338 241.166 204.038 214.046C222.287 210.296 238.038 198.87 247.267 182.685C261.404 158.128 258.142 127.263 239.184 106.203Z"/>
          </svg>
        )
      case 'ollama':
        return (
          <svg width={s} height={s} viewBox="0 0 17 25" fill="currentColor">
            <path d="M4.405.102c.216.096.411.255.588.465.295.348.544.846.734 1.436.191.593.315 1.25.362 1.909.63-.405 1.329-.651 2.049-.723.87-.08 1.73.098 2.48.538.101.06.2.125.297.193.05-.647.172-1.289.36-1.868.19-.591.439-1.087.733-1.436.164-.202.365-.361.589-.466.257-.114.53-.134.796-.048.401.13.745.418 1.016.837.248.383.434.874.561 1.463.231 1.061.271 2.458.116 4.142l.053.045.026.022c.757.654 1.284 1.587 1.563 2.67.435 1.69.216 3.585-.534 4.645l-.018.024.002.003c.417.866.67 1.781.724 2.728l.002.034c.064 1.21-.2 2.428-.814 3.625l-.007.011.01.027c.472 1.315.62 2.639.438 3.962l-.006.044c-.028.193-.122.366-.262.48-.14.114-.314.161-.484.129-.084-.015-.165-.049-.238-.099a1.075 1.075 0 01-.177-.174c-.049-.078-.085-.167-.105-.261-.02-.094-.023-.192-.01-.288.167-1.174.01-2.351-.48-3.549-.046-.111-.066-.234-.059-.356.007-.122.041-.241.099-.344l.004-.007c.604-1.05.854-2.079.8-3.091-.046-.885-.325-1.755-.8-2.583a1.392 1.392 0 00-.107-.187c-.034-.048-.067-.094-.107-.138-.243-.181-.467-.642-.58-1.273-.125-.746-.092-1.514-.114-1.763-.205-.795-.58-1.459-1.105-1.912-.6-.516-1.388-.765-2.385-.693-.13.01-.261-.025-.373-.1a1.266 1.266 0 01-.336-.39c-.314-.756-.772-1.297-1.343-1.632a2.509 2.509 0 00-1.039-.311c-.331-.014-.657.071-.925.26a1.232 1.232 0 00-.118-.103c-.378-.27-.877-.255-1.353-.218-.369.029-.72.091-1.043.225l-.048-.088c-.144-.325-.364-.612-.615-.83-.223-.192-.521-.307-.837-.328-.266-.017-.54.063-.763.225-.216-.096-.411-.255-.588-.465z"/>
          </svg>
        )
      case 'router9':
        return (
          <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
          </svg>
        )
      case 'cliproxy':
        return (
          <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
            <path d="M20 18c1.1 0 1.99-.9 1.99-2L22 6c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2H0v2h24v-2h-4zM4 6h16v10H4V6z"/>
          </svg>
        )
      case 'xiaomi':
        return (
          <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
          </svg>
        )
      case 'kimi':
        return (
          <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
          </svg>
        )
      case 'foundry':
        return (
          <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
            <path d="M2 2h9.5v9.5H2V2zm10.5 0H22v9.5h-9.5V2zM2 12.5h9.5V22H2v-9.5zm10.5 0H22V22h-9.5v-9.5z"/>
          </svg>
        )
      default:
        return (
          <span className="font-bold text-sm">{provider.id.charAt(0).toUpperCase()}</span>
        )
    }
  }

  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center rounded-xl ring-1 transition-all',
        sizeClasses[size],
        brand.iconClass,
      )}
      aria-hidden="true"
    >
      {renderLogo()}
    </div>
  )
}

// ─── Section header ──────────────────────────────────────────────────────────

function SectionHeader({ label, count, icon: Icon }: { label: string; count: number; icon?: React.ComponentType<{ size?: number; className?: string }> }) {
  return (
    <div className="flex items-center gap-2.5 pb-2">
      {Icon && <Icon size={14} className="text-(--color-text-muted)" aria-hidden="true" />}
      <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">{label}</h2>
      <span className="rounded-full bg-(--color-accent-subtle) px-2 py-0.5 font-mono text-[0.65rem] tabular-nums text-(--color-text-muted)">
        {count}
      </span>
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
          'group relative flex w-full items-center gap-3.5 rounded-xl border bg-(--bg-card) px-4 py-3.5 text-left transition-all duration-150',
          'hover:border-(--color-border-strong) hover:shadow-md hover:shadow-black/5',
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
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) opacity-0 transition-all hover:bg-(--bg-key) hover:text-(--color-text) group-hover:opacity-100"
              aria-label={`${provider.label} documentation`}
            >
              <ExternalLink size={13} aria-hidden="true" />
            </span>
          )}

          {/* Expand arrow */}
          <ChevronRight size={14} className="shrink-0 text-(--color-text-muted) transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-(--color-text)" aria-hidden="true" />
        </div>
      </button>
    )
  }

  // ── Expanded card ──────────────────────────────────────────────────────
  return (
    <>
      <Card size="sm" className={cn(
        'rounded-xl transition-all duration-150',
        isConfiguredButUnreachable
          ? 'border-(--color-error)/30'
          : isConnected
            ? 'border-(--color-success)/25'
            : 'border-(--color-border)',
      )}>
        <CardContent className="space-y-4">
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
          <div className="rounded-xl border border-(--color-border-subtle) bg-(--bg-page)/50 p-4">
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
        </CardContent>
      </Card>

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
    <div className="overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-page)/50">
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
          className={cn('shrink-0 text-(--color-text-muted) transition-transform duration-150', expanded && 'rotate-180')}
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
          'flex h-7 min-w-[5rem] items-center justify-center gap-1.5 rounded-lg px-2.5 text-[0.7rem] font-medium transition-all md:h-6',
          selected
            ? 'bg-(--color-success) text-white shadow-sm'
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
  const isMobile = useIsMobile()
  const settingsNavigate = useSettingsNavigate()
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
    <>
      {/* ── Page header ────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-(--z-panel) flex h-14 shrink-0 items-center gap-3 border-b border(--color-border) bg-(--bg-page) px-4">
        {isMobile && (
          <button
            type="button"
            onClick={() => settingsNavigate('/settings')}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Back to settings"
          >
            <ArrowLeft size={16} />
          </button>
        )}
        <KeyRound size={16} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Providers</h1>
        {connectedProviders.length > 0 && (
          <span className="rounded-full bg-(--color-success-subtle) px-2.5 py-1 text-[0.65rem] font-semibold text-(--color-success)">
            {connectedProviders.length} connected
          </span>
        )}
      </header>

      {/* ── Content ────────────────────────────────────────────────────────── */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 pt-6 pb-10 sm:px-6">
          {/* ── Intro + search ──────────────────────────────────────────────── */}
          <div className="space-y-4">
            <p className="text-sm leading-relaxed text-(--color-text-muted)">
              Connect a model provider so EvoFlux can run agents. API keys are stored locally; OAuth tokens are cached on your machine.
            </p>

            {!providersQ.isLoading && providers.length > 0 && (
              <div className="relative flex h-10 items-center rounded-xl border border-(--color-border) bg-(--bg-card) transition-colors focus-within:border-(--focus-ring) focus-within:ring-3 focus-within:ring-(--focus-ring)/30">
                <Search
                  size={14}
                  className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-(--color-text-muted)"
                  aria-hidden="true"
                />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search providers…"
                  aria-label="Search providers"
                  className="h-full flex-1 border-0 bg-transparent pr-4 pl-10 text-sm focus:ring-0 focus-visible:ring-0"
                />
                {!providersQ.isLoading && (
                  <span className="pr-3.5 font-mono text-xs tabular-nums text-(--color-text-muted)">
                    {totalFiltered} {totalFiltered === 1 ? 'provider' : 'providers'}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* ── Loading / Error states ──────────────────────────────────────── */}
          {providersQ.isLoading && (
            <div className="flex items-center gap-2 py-12 text-sm text-(--color-text-muted)">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Loading providers…
            </div>
          )}
          {providersQ.error && (
            <div className="mt-4 flex items-start gap-3 rounded-xl border border-(--color-error)/30 bg-(--color-error)/10 p-4">
              <AlertCircle size={16} className="mt-0.5 shrink-0 text-(--color-error)" aria-hidden="true" />
              <div>
                <p className="text-sm font-medium text-(--color-error)">Failed to load providers</p>
                <p className="mt-1 text-xs text-(--color-text-muted)">
                  {providersQ.error instanceof Error ? providersQ.error.message : String(providersQ.error)}
                </p>
              </div>
            </div>
          )}

          {/* ── Provider groups ─────────────────────────────────────────────── */}
          {!providersQ.isLoading && !providersQ.error && (
            <div className="mt-8 space-y-8">
              {/* Connected providers */}
              {filteredConnected.length > 0 && (
                <section>
                  <SectionHeader label="Connected" count={filteredConnected.length} icon={CheckCircle2} />
                  <div className="space-y-3">
                    {filteredConnected.map((provider) => (
                      <ProviderCard key={provider.id} provider={provider} />
                    ))}
                  </div>
                </section>
              )}

              {/* Available providers */}
              {filteredAvailable.length > 0 && (
                <section>
                  <SectionHeader label="Available" count={filteredAvailable.length} icon={KeyRound} />
                  <div className="space-y-3">
                    {filteredAvailable.map((provider) => (
                      <ProviderCard key={provider.id} provider={provider} />
                    ))}
                  </div>
                </section>
              )}

              {/* Empty search */}
              {totalFiltered === 0 && search.trim() && (
                <div className="py-12 text-center">
                  <Search size={24} className="mx-auto mb-3 text-(--color-text-muted)/50" aria-hidden="true" />
                  <p className="text-sm text-(--color-text-muted)">
                    No providers match &ldquo;{search}&rdquo;
                  </p>
                  <button
                    type="button"
                    onClick={() => setSearch('')}
                    className="mt-2 text-sm font-medium text-(--color-accent) hover:text-(--color-accent-foreground)"
                  >
                    Clear search
                  </button>
                </div>
              )}

              {/* No providers at all */}
              {providers.length === 0 && !providersQ.isLoading && (
                <div className="py-12 text-center">
                  <KeyRound size={32} className="mx-auto mb-4 text-(--color-text-muted)/30" aria-hidden="true" />
                  <p className="text-sm font-medium text-(--color-text)">No providers available</p>
                  <p className="mt-1 text-xs text-(--color-text-muted)">
                    Check your backend connection and try again.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
