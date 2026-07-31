/**
 * /settings/sandbox — user-editable deny-list of glob patterns the agent
 * cannot access (system-level files like ``.env``, ``db/``, etc).
 */
import { useMemo, useState } from 'react'
import { AlertTriangle, ChevronDown, Plus, Save, Shield, Trash2 } from 'lucide-react'

import {
  useSandboxSettingsQuery,
  useUpdateSandboxSettingsMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Switch } from '@/components/ui/switch'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export function SandboxSettingsPage() {
  const { data, isLoading, error, refetch } = useSandboxSettingsQuery()
  const updateMut = useUpdateSandboxSettingsMutation()
  const push = useToastStore((s) => s.push)

  // Local working copy of the deny-list. Rebases onto each fresh server
  // snapshot via the snapshot identity (no effect needed).
  const [draft, setDraft] = useState<{
    source: readonly string[]
    patterns: string[]
    sourceWorktreeLocation: 'repository' | 'user_data'
    worktreeLocation: 'repository' | 'user_data'
    sourceNativeIsolation: 'required' | 'best_effort'
    nativeIsolation: 'required' | 'best_effort'
    sourceAllowNetwork: boolean
    allowNetwork: boolean
    sourceInheritEnvironment: boolean
    inheritEnvironment: boolean
    sourceLoadShellProfile: boolean
    loadShellProfile: boolean
    sourceOutboundDataPolicy: 'block' | 'redact' | 'off'
    outboundDataPolicy: 'block' | 'redact' | 'off'
    sourceOutboundPiiPolicy: 'off' | 'standard' | 'strict'
    outboundPiiPolicy: 'off' | 'standard' | 'strict'
    sourceMaxExecutionSeconds: number
    maxExecutionSeconds: number
    sourceMaxOutputBytes: number
    maxOutputBytes: number
  }>({
    source: [],
    patterns: [],
    sourceWorktreeLocation: 'repository',
    worktreeLocation: 'repository',
    sourceNativeIsolation: 'best_effort',
    nativeIsolation: 'best_effort',
    sourceAllowNetwork: false,
    allowNetwork: false,
    sourceInheritEnvironment: false,
    inheritEnvironment: false,
    sourceLoadShellProfile: false,
    loadShellProfile: false,
    sourceOutboundDataPolicy: 'redact',
    outboundDataPolicy: 'redact',
    sourceOutboundPiiPolicy: 'standard',
    outboundPiiPolicy: 'standard',
    sourceMaxExecutionSeconds: 120,
    maxExecutionSeconds: 120,
    sourceMaxOutputBytes: 131072,
    maxOutputBytes: 131072,
  })

  const serverPatterns = data?.denied_patterns
  if (
    serverPatterns
    && (
      serverPatterns !== draft.source
      || data.worktree_location !== draft.sourceWorktreeLocation
    )
  ) {
    setDraft({
      source: serverPatterns,
      patterns: serverPatterns,
      sourceWorktreeLocation: data.worktree_location,
      worktreeLocation: data.worktree_location,
      sourceNativeIsolation: data.native_process_isolation,
      nativeIsolation: data.native_process_isolation,
      sourceAllowNetwork: data.allow_network,
      allowNetwork: data.allow_network,
      sourceInheritEnvironment: data.inherit_shell_environment,
      inheritEnvironment: data.inherit_shell_environment,
      sourceLoadShellProfile: data.load_shell_profile,
      loadShellProfile: data.load_shell_profile,
      sourceOutboundDataPolicy: data.outbound_data_policy,
      outboundDataPolicy: data.outbound_data_policy,
      sourceOutboundPiiPolicy: data.outbound_pii_policy,
      outboundPiiPolicy: data.outbound_pii_policy,
      sourceMaxExecutionSeconds: data.max_execution_seconds,
      maxExecutionSeconds: data.max_execution_seconds,
      sourceMaxOutputBytes: data.max_output_bytes,
      maxOutputBytes: data.max_output_bytes,
    })
  }
  const patterns = draft.patterns
  const setPatterns = (next: string[] | ((prev: string[]) => string[])) =>
    setDraft((d) => ({
      ...d,
      patterns: typeof next === 'function' ? next(d.patterns) : next,
    }))

  const dirty = useMemo(() => {
    const a = draft.source
    if (a.length !== patterns.length) return true
    if (a.some((p, i) => p !== patterns[i])) return true
    return (
      draft.sourceWorktreeLocation !== draft.worktreeLocation
      || draft.sourceNativeIsolation !== draft.nativeIsolation
      || draft.sourceAllowNetwork !== draft.allowNetwork
      || draft.sourceInheritEnvironment !== draft.inheritEnvironment
      || draft.sourceLoadShellProfile !== draft.loadShellProfile
      || draft.sourceOutboundDataPolicy !== draft.outboundDataPolicy
      || draft.sourceOutboundPiiPolicy !== draft.outboundPiiPolicy
      || draft.sourceMaxExecutionSeconds !== draft.maxExecutionSeconds
      || draft.sourceMaxOutputBytes !== draft.maxOutputBytes
    )
  }, [
    draft.allowNetwork,
    draft.inheritEnvironment,
    draft.loadShellProfile,
    draft.maxExecutionSeconds,
    draft.maxOutputBytes,
    draft.nativeIsolation,
    draft.outboundDataPolicy,
    draft.outboundPiiPolicy,
    draft.source,
    draft.sourceAllowNetwork,
    draft.sourceInheritEnvironment,
    draft.sourceLoadShellProfile,
    draft.sourceMaxExecutionSeconds,
    draft.sourceMaxOutputBytes,
    draft.sourceNativeIsolation,
    draft.sourceOutboundDataPolicy,
    draft.sourceOutboundPiiPolicy,
    draft.sourceWorktreeLocation,
    draft.worktreeLocation,
    patterns,
  ])

  const updateAt = (idx: number, value: string) =>
    setPatterns((prev) => prev.map((p, i) => (i === idx ? value : p)))

  const removeAt = (idx: number) =>
    setPatterns((prev) => prev.filter((_, i) => i !== idx))

  const addRow = () => setPatterns((prev) => [...prev, ''])

  const handleSave = async () => {
    const cleaned = patterns.map((p) => p.trim()).filter(Boolean)
    const maxExecutionSeconds = Math.min(
      3600,
      Math.max(5, Math.round(draft.maxExecutionSeconds || 120)),
    )
    const maxOutputBytes = Math.min(
      1048576,
      Math.max(4096, Math.round(draft.maxOutputBytes || 131072)),
    )
    try {
      const saved = await updateMut.mutateAsync({
        denied_patterns: cleaned,
        worktree_location: draft.worktreeLocation,
        native_process_isolation: draft.nativeIsolation,
        allow_network: draft.allowNetwork,
        inherit_shell_environment: draft.inheritEnvironment,
        load_shell_profile: draft.loadShellProfile,
        outbound_data_policy: draft.outboundDataPolicy,
        outbound_pii_policy: draft.outboundPiiPolicy,
        max_execution_seconds: maxExecutionSeconds,
        max_output_bytes: maxOutputBytes,
      })
      setDraft({
        source: saved.denied_patterns,
        patterns: saved.denied_patterns,
        sourceWorktreeLocation: saved.worktree_location,
        worktreeLocation: saved.worktree_location,
        sourceNativeIsolation: saved.native_process_isolation,
        nativeIsolation: saved.native_process_isolation,
        sourceAllowNetwork: saved.allow_network,
        allowNetwork: saved.allow_network,
        sourceInheritEnvironment: saved.inherit_shell_environment,
        inheritEnvironment: saved.inherit_shell_environment,
        sourceLoadShellProfile: saved.load_shell_profile,
        loadShellProfile: saved.load_shell_profile,
        sourceOutboundDataPolicy: saved.outbound_data_policy,
        outboundDataPolicy: saved.outbound_data_policy,
        sourceOutboundPiiPolicy: saved.outbound_pii_policy,
        outboundPiiPolicy: saved.outbound_pii_policy,
        sourceMaxExecutionSeconds: saved.max_execution_seconds,
        maxExecutionSeconds: saved.max_execution_seconds,
        sourceMaxOutputBytes: saved.max_output_bytes,
        maxOutputBytes: saved.max_output_bytes,
      })
      push({
        tone: 'success',
        title: 'Sandbox saved',
        description: `${cleaned.length} pattern${cleaned.length === 1 ? '' : 's'} active.`,
      })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Save failed',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  return (
    <SettingsPage
      icon={Shield}
      title="Sandbox"
      lede={
        <>
          Agents can access only the active workspace, explicitly attached repositories,
          read-only roots, and session artifacts. Sensitive glob patterns are enforced
          inside those roots too. Use{' '}
          <code className="rounded bg-(--bg-key) px-1 py-0.5 font-mono text-xs">**</code> for any depth
          and <code className="rounded bg-(--bg-key) px-1 py-0.5 font-mono text-xs">*</code> for one
          segment. <SandboxHelpPopover />
        </>
      }
      actions={
        <div className="flex items-center gap-2">
          {dirty && (
            <span className="text-xs text-(--color-text-muted)" aria-live="polite">
              Unsaved
            </span>
          )}
          <Button
            size="sm"
            className="min-h-11 md:min-h-0"
            onClick={handleSave}
            disabled={!dirty || updateMut.isPending}
          >
            <Save size={12} aria-hidden="true" />
            {updateMut.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      }
    >
      <SettingsAsyncBoundary
        loading={isLoading}
        hasData={Boolean(data)}
        error={error}
        variant="detail"
        loadingLabel="Loading sandbox settings"
        errorTitle="Failed to load sandbox settings"
        onRetry={() => void refetch()}
      >
      <div className="space-y-10">
      {data && (
        <SettingsGroup
          title="Outbound data protection"
          description={
            <>
              Applied to a provider-only copy immediately before each model request.
              Local conversation history remains unchanged.{' '}
              <OutboundProtectionHelpPopover />
            </>
          }
        >
          <SettingsRow
            label="Sensitive text"
            description="Detects configured credential values, private keys, authorization headers, credentialed URLs, provider tokens, JWTs, and secret assignments."
            control={
              <SegmentedControl
                options={[
                  { value: 'off', label: 'Off' },
                  { value: 'redact', label: 'Mask' },
                  { value: 'block', label: 'Block' },
                ]}
                value={draft.outboundDataPolicy}
                onChange={(outboundDataPolicy) =>
                  setDraft((current) => ({ ...current, outboundDataPolicy }))
                }
                layoutId="sandbox-outbound-data-policy"
                ariaLabel="Outbound sensitive data policy"
              />
            }
          />
          <SettingsRow
            label="Personal data"
            description="Uses stable placeholders such as [EMAIL_1] and [PHONE_1], preserving repeated references without sending the original values."
            control={
              <SegmentedControl
                options={[
                  { value: 'off', label: 'Off' },
                  { value: 'standard', label: 'Standard' },
                  { value: 'strict', label: 'Strict' },
                ]}
                value={draft.outboundPiiPolicy}
                onChange={(outboundPiiPolicy) =>
                  setDraft((current) => ({ ...current, outboundPiiPolicy }))
                }
                layoutId="sandbox-outbound-pii-policy"
                ariaLabel="Outbound personal data policy"
              />
            }
          />
          <div className="px-4 py-4 sm:px-5">
            <SettingsCallout
              tone={
                draft.outboundDataPolicy === 'off'
                || draft.outboundPiiPolicy === 'off'
                  ? 'warning'
                  : 'info'
              }
              icon={
                draft.outboundDataPolicy === 'off'
                || draft.outboundPiiPolicy === 'off'
                  ? AlertTriangle
                  : Shield
              }
            >
              <div className="space-y-1">
                <p>
                  Credentials:{' '}
                  {draft.outboundDataPolicy === 'block'
                    ? 'requests with detected secrets are stopped before the provider call.'
                    : draft.outboundDataPolicy === 'redact'
                      ? 'detected values are replaced with [REDACTED:…] in the provider payload.'
                      : 'detected secrets are sent without masking.'}
                </p>
                <p>
                  Personal data:{' '}
                  {draft.outboundPiiPolicy === 'standard'
                    ? 'email, phone, valid payment cards, and public IP addresses are pseudonymized.'
                    : draft.outboundPiiPolicy === 'strict'
                      ? 'Standard coverage plus all IPs and structured names, addresses, and identifiers.'
                      : 'email, phone, payment cards, and IP addresses are sent without masking.'}
                </p>
                <p>
                  Binary image and document contents cannot be reliably masked; use
                  denied patterns to prevent sensitive files from being read.
                </p>
              </div>
            </SettingsCallout>
          </div>
        </SettingsGroup>
      )}

      {data && (
        <SettingsGroup
          title="Process security"
          description="Controls applied to every shell command, including commands executed inside delegated worktrees."
        >
          <SettingsRow
            label="Native process isolation"
            description={
              data.native_backend
                ? `Detected backend: ${data.native_backend}. Required mode fails closed if it becomes unavailable.`
                : 'No native backend detected. Required mode blocks shell execution instead of falling back.'
            }
            control={
              <SegmentedControl
                options={[
                  { value: 'required', label: 'Required' },
                  { value: 'best_effort', label: 'Best effort' },
                ]}
                value={draft.nativeIsolation}
                onChange={(nativeIsolation) =>
                  setDraft((current) => ({ ...current, nativeIsolation }))
                }
                layoutId="sandbox-native-isolation"
                ariaLabel="Native process isolation"
              />
            }
          />
          <SettingsRow
            label="Network access"
            description="Allow model-controlled shell processes to open network connections. Keep disabled unless builds or package installation require it."
            control={
              <Switch
                checked={draft.allowNetwork}
                onCheckedChange={(allowNetwork) =>
                  setDraft((current) => ({ ...current, allowNetwork }))
                }
                aria-label="Allow sandbox network access"
              />
            }
          />
          <SettingsRow
            label="Inherit host environment"
            description="Expose host environment variables to shell commands. Disabled passes only PATH, locale, terminal and temporary-directory values."
            control={
              <Switch
                checked={draft.inheritEnvironment}
                onCheckedChange={(inheritEnvironment) =>
                  setDraft((current) => ({ ...current, inheritEnvironment }))
                }
                aria-label="Inherit host shell environment"
              />
            }
          />
          <SettingsRow
            label="Load shell profile"
            description="Source .zshrc or .bashrc before commands. Profiles can execute code and export credentials, so this is disabled by default."
            control={
              <Switch
                checked={draft.loadShellProfile}
                onCheckedChange={(loadShellProfile) =>
                  setDraft((current) => ({ ...current, loadShellProfile }))
                }
                aria-label="Load shell profile"
              />
            }
          />
          <SettingsRow
            label="Maximum execution time"
            description="Hard cap for foreground shell commands, including a larger timeout requested by an agent."
            htmlFor="sandbox-max-execution"
            control={
              <div className="flex items-center gap-2">
                <Input
                  id="sandbox-max-execution"
                  type="number"
                  min={5}
                  max={3600}
                  value={draft.maxExecutionSeconds}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      maxExecutionSeconds: Number(event.target.value),
                    }))
                  }
                  className="h-8 w-24 text-right font-mono"
                />
                <span className="text-xs text-(--color-text-muted)">seconds</span>
              </div>
            }
          />
          <SettingsRow
            label="Maximum inline output"
            description="Output beyond this limit is moved to a session artifact instead of being returned directly to the model."
            htmlFor="sandbox-max-output"
            control={
              <div className="flex items-center gap-2">
                <Input
                  id="sandbox-max-output"
                  type="number"
                  min={4}
                  max={1024}
                  value={Math.round(draft.maxOutputBytes / 1024)}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      maxOutputBytes: Number(event.target.value) * 1024,
                    }))
                  }
                  className="h-8 w-24 text-right font-mono"
                />
                <span className="text-xs text-(--color-text-muted)">KiB</span>
              </div>
            }
          />
          {(draft.allowNetwork || draft.inheritEnvironment || draft.loadShellProfile) && (
            <div className="px-4 py-4 sm:px-5">
              <SettingsCallout tone="warning" icon={AlertTriangle}>
                This configuration exposes additional host capabilities to agent-run
                commands. Enable only what the active project requires.
              </SettingsCallout>
            </div>
          )}
        </SettingsGroup>
      )}

      {data && (
        <SettingsGroup
          title="Managed worktrees"
          description="Choose where EvoFlux creates isolated Git worktrees. Existing worktrees in either location remain recognized and removable."
        >
          <div className="space-y-3 px-3 py-3">
            <SegmentedControl
              options={[
                { value: 'repository', label: 'Inside repository' },
                { value: 'user_data', label: 'User data directory' },
              ]}
              value={draft.worktreeLocation}
              onChange={(worktreeLocation) =>
                setDraft((current) => ({ ...current, worktreeLocation }))
              }
              layoutId="sandbox-worktree-location"
              ariaLabel="Managed worktree location"
            />
            <p className="text-xs leading-relaxed text-(--color-text-muted)">
              {draft.worktreeLocation === 'repository' ? (
                <>
                  New worktrees are stored at{' '}
                  <code className="font-mono">&lt;repository&gt;/.evoflux/worktrees</code>.
                  EvoFlux adds this directory to the repository-local Git exclude file,
                  without modifying <code className="font-mono">.gitignore</code>.
                </>
              ) : (
                <>
                  New worktrees are stored under the EvoFlux data directory in your user
                  profile. This keeps repository folders smaller but makes worktrees less
                  discoverable beside their source.
                </>
              )}
            </p>
          </div>
        </SettingsGroup>
      )}

      {data && patterns.length === 0 && (
        <SettingsGroup title="Denied patterns" bare>
          <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-(--color-border) p-10 text-center">
            <p className="text-sm font-medium text-(--color-text)">Nothing is blocked yet</p>
            <p className="max-w-sm text-xs leading-relaxed text-(--color-text-muted)">
              Workspace allowlists remain active. Add a pattern to additionally block files like{' '}
              <code className="font-mono">.env</code> or folders like{' '}
              <code className="font-mono">secrets/</code>.
            </p>
            <Button size="sm" className="min-h-11 md:min-h-0" onClick={addRow}>
              <Plus size={12} aria-hidden="true" />
              Add pattern
            </Button>
          </div>
        </SettingsGroup>
      )}

      {data && patterns.length > 0 && (
        <SettingsGroup
          title="Denied patterns"
          description={`${patterns.length} ${patterns.length === 1 ? 'pattern is' : 'patterns are'} matched with logical OR. One match blocks access.`}
          actions={
            <Button size="sm" variant="outline" className="min-h-11 md:min-h-0" onClick={addRow}>
              <Plus size={12} aria-hidden="true" />
              Add
            </Button>
          }
        >
          <ul>
            {patterns.map((pattern, idx) => (
              <li
                key={idx}
                className="flex items-center gap-2 px-3 py-2 not-last:border-b not-last:border-(--color-border-subtle)"
              >
                <Input
                  value={pattern}
                  onChange={(e) => updateAt(idx, e.target.value)}
                  placeholder="**/.env"
                  aria-label={`Pattern ${idx + 1}`}
                  className="h-9 border-transparent bg-transparent font-mono text-sm focus-visible:border-(--color-border)"
                />
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        className="size-11 shrink-0 md:size-7"
                        onClick={() => removeAt(idx)}
                        aria-label={`Remove pattern ${idx + 1}`}
                      >
                        <Trash2 size={13} />
                      </Button>
                    }
                  />
                  <TooltipContent>Remove</TooltipContent>
                </Tooltip>
              </li>
            ))}
          </ul>
        </SettingsGroup>
      )}
      </div>
      </SettingsAsyncBoundary>
    </SettingsPage>
  )
}

// ─── Help popover ──────────────────────────────────────────────────────────

function OutboundProtectionHelpPopover() {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            className="inline-flex min-h-11 items-center gap-0.5 rounded text-(--color-text) underline underline-offset-2 hover:opacity-80 focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40 focus-visible:outline-none md:min-h-0"
          >
            Learn more
            <ChevronDown
              size={12}
              aria-hidden="true"
              className={cn('transition-transform', open && 'rotate-180')}
            />
          </button>
        }
      />
      <PopoverContent
        className="w-[min(27rem,calc(100vw-1rem))] gap-4 p-4"
        align="start"
      >
        <div className="space-y-1">
          <p className="text-sm font-medium text-(--color-text)">How masking works</p>
          <p className="text-xs leading-relaxed text-(--color-text-muted)">
            EvoFlux scans the final text payload after tools and prompts are assembled,
            but before the request is handed to the model provider.
          </p>
        </div>

        <ol className="space-y-2 text-xs leading-relaxed text-(--color-text-muted)">
          <li>
            <span className="font-medium text-(--color-text)">1. Detect — </span>
            matches saved credential values and recognizable private keys, authorization
            headers, provider tokens, and personal data enabled by the selected PII
            policy.
          </li>
          <li>
            <span className="font-medium text-(--color-text)">2. Protect — </span>
            secrets use typed redaction labels. Personal data uses stable aliases, so
            the same email or phone remains recognizable as the same entity.
          </li>
          <li>
            <span className="font-medium text-(--color-text)">3. Send a copy — </span>
            only the protected copy goes to the provider. The original conversation
            remains available locally.
          </li>
        </ol>

        <div className="space-y-2 rounded-lg border border-(--color-border-subtle) bg-(--bg-key)/50 p-3">
          <div>
            <span className="text-[10px] font-medium tracking-wide text-(--color-text-faint) uppercase">
              Original text
            </span>
            <code className="mt-1 block break-all font-mono text-xs text-(--color-text)">
              Authorization: Bearer sk-live-example
              <br />
              linh@example.com · +84 912 345 678
            </code>
          </div>
          <div className="border-t border-(--color-border-subtle) pt-2">
            <span className="text-[10px] font-medium tracking-wide text-(--color-text-faint) uppercase">
              Provider receives
            </span>
            <code className="mt-1 block break-all font-mono text-xs text-(--color-text)">
              Authorization: Bearer [REDACTED:authorization]
              <br />
              [EMAIL_1] · [PHONE_1]
            </code>
          </div>
        </div>

        <SettingsCallout tone="warning" icon={AlertTriangle}>
          Standard masks email, phone, valid payment cards, and public IPs. Strict
          also masks private IPs and structured name, address, and ID fields. Neither
          mode can inspect images or opaque binary files.
        </SettingsCallout>
      </PopoverContent>
    </Popover>
  )
}

interface PatternExample {
  pattern: string
  description: string
}

const EXAMPLES: readonly PatternExample[] = [
  { pattern: '**/.env', description: 'Any file named .env, at any depth' },
  { pattern: '**/.env.*', description: 'Variants like .env.local, .env.prod' },
  { pattern: 'secrets/**', description: 'Everything under a secrets/ folder' },
  { pattern: '**/*.pem', description: 'PEM keys anywhere in the tree' },
  { pattern: '**/id_rsa*', description: 'SSH private keys (and .pub if you wish)' },
  { pattern: 'db/**', description: 'Local database files in db/' },
]

/**
 * Inline help: glob primer + concrete examples. Read-only reference.
 * Triggered by a text-link "See examples" button at the end of the
 * helper paragraph. Controlled state so the chevron can flip while open.
 */
function SandboxHelpPopover() {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            className="inline-flex min-h-11 items-center gap-0.5 rounded text-(--color-text) underline-offset-2 hover:underline focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40 focus-visible:outline-none md:min-h-0"
          >
            See examples
            <ChevronDown
              size={12}
              aria-hidden="true"
              className={cn('transition-transform', open && 'rotate-180')}
            />
          </button>
        }
      />
      <PopoverContent className="w-[min(20rem,calc(100vw-1rem))] gap-3 p-3" align="start">
        <ul className="flex flex-col gap-1.5">
          {EXAMPLES.map((ex) => (
            <li key={ex.pattern} className="flex flex-col gap-0.5">
              <code className="self-start rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-xs text-(--color-text)">
                {ex.pattern}
              </code>
              <span className="text-xs leading-snug text-(--color-text-muted)">{ex.description}</span>
            </li>
          ))}
        </ul>

        <p className="border-t border-(--color-border) pt-2 text-xs leading-snug text-(--color-text-muted)">
          Built-in database, state and cache paths are always denied. Patterns also
          apply inside active workspaces.
        </p>
      </PopoverContent>
    </Popover>
  )
}
