/**
 * AgentForm — hybrid form for agent .md files.
 *
 * Modes:
 *   - **form**: structured fields for frontmatter + textarea for the
 *     system prompt body. Changes are serialised to canonical YAML on
 *     save. Recommended for most users.
 *   - **raw**: plain textarea with the full .md contents (frontmatter +
 *     body). Power users can hand-edit nested fields the form doesn't
 *     model (e.g. custom hook configuration).
 *
 * Switching form → raw preserves any extra YAML fields the form doesn't
 * know about by re-using the previous raw content whenever possible.
 * Switching raw → form re-parses the current raw text.
 *
 * The mode is a controlled prop so the editor's sticky header (rendered
 * by the parent route) hosts the Form/Raw toggle next to Save — keeping
 * top-of-page real estate consistent across all editor pages.
 */
import { useMemo, useState } from 'react'
import {
  AlertCircle,
  Boxes,
  BrainCircuit,
  Check,
  ChevronDown,
  FileText,
  LockKeyhole,
  UserRound,
  type LucideIcon,
} from 'lucide-react'

import { ModelOptions } from '@/components/model-picker/ModelOptions'
import { ProviderBrandIcon } from '@/components/providers/ProviderBrandIcon'
import { SettingsGroup } from '@/components/settings/SettingsLayout'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { isBuiltInAgentName } from '@/lib/agent-visuals'
import {
  buildThinkingOptions,
  providerOf,
  reconcileThinkingLevel,
  shortModelName,
  type ModelOption,
} from '@/lib/model-settings'

import { useAgentFilesQuery, useMcpServersQuery, useRegistryQuery } from '@/queries'
import { useActiveSkillDiscoveryScope } from '@/hooks/useActiveSkillDiscoveryScope'
import type { SkillMode } from '@/api/types'
import { MultiSelect, type MultiSelectOption } from './MultiSelect'
import {
  combinePreservingUnknown,
  normalizeYamlScalarContinuations,
  splitFrontmatter,
  unquoteYamlScalar,
  type AgentFrontmatter,
} from './frontmatter'
import {
  validateAgentName,
  validateDescription,
  validateModel,
} from './schema'

export interface AgentFormValue {
  /** Current raw .md content (frontmatter + body). Always authoritative. */
  raw: string
}

interface Props {
  initial: string
  /** Agent file path from the API route, e.g. "EvoFlux" or "coding/coder". */
  agentPath?: string
  /** Fires on every keystroke with the up-to-date raw content. */
  onChange: (raw: string) => void
  /** Disabled when the caller is mid-save / validation. */
  disabled?: boolean
  /** When creating a new agent the name is still editable. */
  isNew?: boolean
  /** Controlled Form/Raw mode — owned by the parent so the sub-header
   *  toggle stays in sync with the form body. */
  mode: 'form' | 'raw'
  onModeChange: (next: 'form' | 'raw') => void
  /** Runtime mode used to resolve mode-specific skill collisions. */
  skillMode?: SkillMode
  /** Project repositories; falls back to the active coding workspace. */
  workspaceRoots?: readonly string[]
}

export function AgentForm({
  initial,
  agentPath,
  onChange,
  disabled,
  isNew,
  mode,
  onModeChange,
  skillMode,
  workspaceRoots,
}: Props) {
  const [raw, setRaw] = useState(initial)

  // Seed form state from the initial raw content. Subsequent edits update
  // `raw` via `updateFromForm` / `updateFromRaw` — never from `initial`.
  const seed = useMemo(() => parseFormState(initial), [initial])
  const [fm, setFm] = useState<AgentFrontmatter>(seed.fm)
  const [body, setBody] = useState(seed.body)
  const [parseError, setParseError] = useState<string | null>(seed.error)

  // If the parent swaps `initial` (e.g. navigating between agents), adopt
  // the new seed. We track the last-seen initial in state so this is a
  // plain derived-state update rather than an effect.
  const [lastInitial, setLastInitial] = useState(initial)
  if (initial !== lastInitial) {
    setLastInitial(initial)
    setRaw(initial)
    setFm(seed.fm)
    setBody(seed.body)
    setParseError(seed.error)
  }

  // When the parent flips mode, re-parse if going back to form so we don't
  // show stale field values.
  const [lastMode, setLastMode] = useState(mode)
  if (mode !== lastMode) {
    setLastMode(mode)
    if (mode === 'form') {
      const p = parseFormState(raw)
      setFm(p.fm)
      setBody(p.body)
      setParseError(p.error)
    }
  }

  const agentMode = skillMode ?? (agentPath?.startsWith('coding/') ? 'coding' : 'work')
  const activeSkillScope = useActiveSkillDiscoveryScope(agentMode)
  const registry = useRegistryQuery(
    workspaceRoots?.length
      ? { workspaces: workspaceRoots, mode: agentMode }
      : activeSkillScope,
  )
  const mcpServers = useMcpServersQuery()
  const agentFiles = useAgentFilesQuery()

  // Hide ``mcp_<server>_<tool>`` entries from the Tools picker — they are
  // granted en bloc via the MCP server picker below, so showing them in
  // both places would let the user pick the same capability twice.
  const toolOptions: MultiSelectOption[] =
    registry.data?.tools
      .filter((t) => !t.name.startsWith('mcp_'))
      .map((t) => ({
        value: t.name,
        label: t.name,
        description: t.description,
      })) ?? []

  // Lead-only tools (ask_user, plan mode, worktree…) are never granted to
  // members — used below to hide them from a member agent's tool picker.
  const leadOnlyTools = new Set(
    registry.data?.tools.filter((t) => t.lead_only).map((t) => t.name) ?? [],
  )

  const skillOptions: MultiSelectOption[] =
    registry.data?.skills
      .filter((s) => (s.modes ?? ['work', 'coding']).includes(agentMode))
      .map((s) => ({
        value: s.name,
        label: s.display_name || s.name,
        description: `${s.short_description || s.description}${s.allow_implicit_invocation === false ? ' · explicit catalog' : ''}`,
      })) ?? []

  // Show every server, including disabled / errored ones, so an agent can
  // still reference a server that's temporarily down without the picker
  // silently dropping the chip on save.
  const mcpOptions: MultiSelectOption[] =
    mcpServers.data?.servers.map((s) => {
      const tools = s.tool_names.length
      const detail = `${s.transport} · ${s.state} · ${tools} tool${tools === 1 ? '' : 's'}`
      return {
        value: s.name,
        label: s.name,
        description: detail,
      }
    }) ?? []

  const agentSummary = agentFiles.data?.agents.find((a) => a.name === agentPath)
  const modelOptions = registry.data?.models ?? []

  // Form → raw propagation. Runs whenever a form field changes.
  const updateFromForm = (next: AgentFrontmatter, nextBody: string) => {
    setFm(next)
    setBody(nextBody)
    const r = combinePreservingUnknown(raw, next, nextBody)
    setRaw(r)
    onChange(r)
    setParseError(null)
  }

  // Raw → form propagation. Parsing may fail; we surface the error but
  // still let the user fix it in raw mode.
  const updateFromRaw = (nextRaw: string) => {
    setRaw(nextRaw)
    onChange(nextRaw)
    const p = parseFormState(nextRaw)
    setFm(p.fm)
    setBody(p.body)
    setParseError(p.error)
  }

  return (
    <div className="flex flex-col gap-4">
      {parseError && (
        <ParseErrorBanner
          message={parseError}
          onSwitchToRaw={() => onModeChange('raw')}
        />
      )}

      {mode === 'form' ? (
        <FormFields
          fm={fm}
          body={body}
          disabled={disabled}
          isNew={isNew}
          toolOptions={toolOptions}
          leadOnlyTools={leadOnlyTools}
          skillOptions={skillOptions}
          mcpOptions={mcpOptions}
          modelOptions={modelOptions}
          agentPath={agentPath}
          effectiveTools={agentSummary?.tools}
          updateFromForm={updateFromForm}
        />
      ) : (
        <SettingsGroup
          title="Raw .md"
          description="Edit the raw frontmatter and body. Useful for fields the form doesn't expose (e.g. custom hook configuration)."
        >
          <div className="px-4 py-3.5">
            <Textarea
              value={raw}
              onChange={(e) => updateFromRaw(e.target.value)}
              disabled={disabled}
              rows={28}
              spellCheck={false}
              className="min-h-72 font-mono text-[13px] leading-relaxed"
            />
          </div>
        </SettingsGroup>
      )}
    </div>
  )
}

function ParseErrorBanner({
  message,
  onSwitchToRaw,
}: {
  message: string
  onSwitchToRaw: () => void
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-(--color-error)/35 bg-(--color-error-subtle) px-3 py-2 text-xs text-(--color-error)">
      <AlertCircle size={14} className="mt-0.5 shrink-0" />
      <div className="flex-1">
        <p className="font-medium">Parse error</p>
        <p className="mt-0.5 opacity-90">{message}</p>
      </div>
      <Button size="xs" variant="outline" className="min-h-11 md:min-h-0" onClick={onSwitchToRaw}>
        Open raw
      </Button>
    </div>
  )
}

// ── Form mode ───────────────────────────────────────────────────────────────

/**
 * The Form-mode UI, organised into grouped sections so each concern has a clear title
 * and the form scans top-to-bottom: who → what model → behaviour → tools
 * & skills → system prompt.
 */
function FormFields({
  fm,
  body,
  disabled,
  isNew,
  toolOptions,
  leadOnlyTools,
  skillOptions,
  mcpOptions,
  modelOptions,
  agentPath,
  effectiveTools,
  updateFromForm,
}: {
  fm: AgentFrontmatter
  body: string
  disabled?: boolean
  isNew?: boolean
  toolOptions: MultiSelectOption[]
  leadOnlyTools: Set<string>
  skillOptions: MultiSelectOption[]
  mcpOptions: MultiSelectOption[]
  modelOptions: ModelOption[]
  agentPath?: string
  effectiveTools?: string[]
  updateFromForm: (next: AgentFrontmatter, nextBody: string) => void
}) {
  // Per-field errors computed fresh from zod on render. For the scalar
  // string fields we validate whenever the value is non-empty; empty is
  // handled by the caller's full-form check before save.
  const nameError = isNew ? validateAgentName(fm.name) : null
  const descriptionError = validateDescription(fm.description ?? '')
  const currentModelOptions = useMemo(() => {
    const byId = new Map(modelOptions.map((model) => [model.id, model]))
    const withCurrent: ModelOption[] = [...modelOptions]
    for (const id of [fm.model, fm.fallback_model]) {
      if (!id || byId.has(id) || !id.includes(':')) continue
      const [provider, model] = id.split(':', 2)
      const current = { id, provider, model, vision: false }
      withCurrent.push(current)
      byId.set(id, current)
    }
    return withCurrent
  }, [fm.fallback_model, fm.model, modelOptions])
  const validModelIds = useMemo(
    () => currentModelOptions.map((m) => m.id),
    [currentModelOptions],
  )
  const modelError = validateModel(fm.model ?? '', {
    required: true,
    validValues: validModelIds,
  })
  const fallbackError = validateModel(fm.fallback_model ?? '', {
    validValues: validModelIds,
  })
  const selectedModel = currentModelOptions.find((model) => model.id === fm.model)
  const thinkingOptions = buildThinkingOptions(selectedModel?.thinking_levels ?? [])
  const thinkingValue =
    fm.thinking_level &&
    thinkingOptions.some((option) => option.value === fm.thinking_level)
      ? fm.thinking_level
      : '__default__'
  const hasBuiltInProfile = isBuiltInProfile(fm.name, fm.role, agentPath)
  const implicitToolNames = new Set(['skill', 'todo_manage', 'schedule_task', 'note'])
  // Every agent gets its mode tier's tools — the server's effective
  // toolset (tier grant + implicit adds) minus explicit frontmatter
  // extras is what we show as always-included chips.
  const defaultToolNames = new Set([
    ...(effectiveTools ?? []).filter((tool) => !(fm.tools ?? []).includes(tool)),
    ...(fm.tools_opt_out ?? []),
  ])
  const grantedTools = [...defaultToolNames].filter(
    (tool) => !(fm.tools_opt_out ?? []).includes(tool),
  )
  const isMember = fm.role !== 'lead'
  const extraToolOptions = toolOptions
    .filter((option) => !defaultToolNames.has(option.value))
    .filter((option) => !implicitToolNames.has(option.value))
    // Lead-only tools would be silently skipped by the loader for members
    // — don't offer them in the first place.
    .filter((option) => !(isMember && leadOnlyTools.has(option.value)))
  const extraSkillOptions = skillOptions
  const defaultToolOptions = toolOptions.filter((option) =>
    defaultToolNames.has(option.value),
  )
  const promptWordCount = body.trim() ? body.trim().split(/\s+/).length : 0

  return (
    <div className="flex flex-col gap-5">
      {hasBuiltInProfile && (
        <div className="flex items-start gap-3 rounded-xl border border-(--color-accent)/20 bg-(--color-accent-soft) px-4 py-3.5 text-xs leading-relaxed text-(--color-text-muted)">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-(--bg-card) text-(--color-accent) ring-1 ring-(--color-accent)/20">
            <LockKeyhole size={14} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="font-semibold text-(--color-text)">Built-in EvoFlux profile</p>
            <p className="mt-0.5">
              Default tools and instructions are versioned in EvoFlux. Assigned skills are preloaded for this agent; the remaining catalog stays on demand. Upgrades never overwrite your custom setup.
            </p>
          </div>
        </div>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <AgentSection
          icon={UserRound}
          title="Profile"
          description="Name the agent and make its responsibility obvious to the team."
        >
          <div className="grid gap-4 p-4 sm:p-5 md:grid-cols-2">
            <Field
              label="Name"
              required
              error={nameError}
              hint={
                !isNew
                  ? 'Filename stem; locked after creation.'
                  : 'Letters, digits, ., _, - only.'
              }
            >
              <Input
                type="text"
                value={fm.name}
                onChange={(e) => updateFromForm({ ...fm, name: e.target.value }, body)}
                disabled={disabled || !isNew}
                placeholder="orchestrator"
                aria-invalid={!!nameError || undefined}
                className="min-h-11 font-mono md:min-h-10"
              />
            </Field>

            <Field label="Role" required hint="Each team must have exactly one lead.">
              <Select
                value={fm.role}
                onValueChange={(value) =>
                  value && updateFromForm({ ...fm, role: value as 'lead' | 'member' }, body)
                }
                disabled={disabled}
              >
                <SelectTrigger aria-label="Role" className="min-h-11 w-full md:min-h-10">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="lead">Lead</SelectItem>
                  <SelectItem value="member">Member</SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field
              label="Description"
              error={descriptionError}
              className="md:col-span-2"
              hint="Shown in the roster and when the lead chooses a teammate."
            >
              <Input
                type="text"
                className="min-h-11 md:min-h-10"
                value={fm.description ?? ''}
                onChange={(event) =>
                  updateFromForm({ ...fm, description: event.target.value || null }, body)
                }
                disabled={disabled}
                placeholder="Coordinates the team and delegates focused work."
                aria-invalid={!!descriptionError || undefined}
              />
            </Field>
          </div>
        </AgentSection>

        <AgentSection
          icon={BrainCircuit}
          title="Runtime"
          description="Use the same model and reasoning controls available in chat."
        >
          <div className="grid gap-4 p-4 sm:p-5 md:grid-cols-2">
            <Field label="Primary model" required error={modelError} className="md:col-span-2">
              <ModelCombobox
                value={fm.model ?? ''}
                options={currentModelOptions}
                onChange={(modelId) => {
                  const nextModel = currentModelOptions.find(
                    (model) => model.id === modelId,
                  )
                  updateFromForm(
                    {
                      ...fm,
                      model: modelId,
                      thinking_level: reconcileThinkingLevel(
                        fm.thinking_level,
                        nextModel,
                      ),
                    },
                    body,
                  )
                }}
                disabled={disabled}
                invalid={!!modelError}
              />
            </Field>

            <Field
              label="Thinking"
              hint={
                thinkingOptions.length > 1
                  ? 'Options supported by this model.'
                  : 'No configurable reasoning control.'
              }
            >
              <Select
                value={thinkingValue}
                onValueChange={(value) => {
                  if (value == null) return
                  updateFromForm(
                    { ...fm, thinking_level: value === '__default__' ? null : value },
                    body,
                  )
                }}
                disabled={disabled || thinkingOptions.length === 1}
              >
                <SelectTrigger aria-label="Thinking level" className="min-h-11 w-full md:min-h-10">
                  <SelectValue>
                    {thinkingOptions.find(
                      (option) => (option.value ?? '__default__') === thinkingValue,
                    )?.label ?? 'Default'}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {thinkingOptions.map((option) => (
                    <SelectItem
                      key={option.value ?? '__default__'}
                      value={option.value ?? '__default__'}
                    >
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field
              label="Fallback"
              error={fallbackError}
              hint="Used only if the primary model fails."
            >
              <ModelCombobox
                value={fm.fallback_model ?? ''}
                options={currentModelOptions}
                onChange={(value) =>
                  updateFromForm({ ...fm, fallback_model: value || null }, body)
                }
                disabled={disabled}
                invalid={!!fallbackError}
                allowUnset
                unsetLabel="No fallback"
              />
            </Field>
          </div>
        </AgentSection>
      </div>

      <AgentSection
        icon={Boxes}
        title="Capabilities"
        description="Built-in access stays visible but compact. Add only what this agent needs beyond its team defaults."
        meta={`${(fm.tools ?? []).length + (fm.mcp ?? []).length + (fm.skills ?? []).length} custom · ${(fm.tools_opt_out ?? []).length} disabled`}
      >
        <div className="grid divide-y divide-(--color-border-subtle) lg:grid-cols-3 lg:divide-x lg:divide-y-0">
          <div className="min-w-0 p-4 sm:p-5">
            <Field
              label="Tools"
              hint={
                grantedTools.length > 0
                  ? `${(fm.tools ?? []).length} extra selected.`
                  : `${(fm.tools ?? []).length} selected of ${extraToolOptions.length}.`
              }
            >
              {grantedTools.length > 0 && (
                <CapabilityChips label="Included by team" values={grantedTools} />
              )}
              <MultiSelect
                ariaLabel="Tools"
                options={extraToolOptions}
                value={fm.tools ?? []}
                onChange={(value) => updateFromForm({ ...fm, tools: value }, body)}
                placeholder="Add extra tools…"
              />
              {defaultToolOptions.length > 0 && (
                <div className="mt-3 border-t border-(--color-border-subtle) pt-3">
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-(--color-text-muted)">
                    Disabled team defaults
                  </p>
                  <MultiSelect
                    ariaLabel="Disabled default tools"
                    options={defaultToolOptions}
                    value={fm.tools_opt_out ?? []}
                    onChange={(value) =>
                      updateFromForm({ ...fm, tools_opt_out: value }, body)
                    }
                    placeholder="Disable a default tool…"
                  />
                </div>
              )}
            </Field>
          </div>

          <div className="min-w-0 p-4 sm:p-5">
            <Field
              label="MCP servers"
              hint={
                mcpOptions.length === 0
                  ? 'Configure servers in Settings → MCP.'
                  : `${(fm.mcp ?? []).length} selected of ${mcpOptions.length}.`
              }
            >
              <MultiSelect
                ariaLabel="MCP servers"
                options={mcpOptions}
                value={fm.mcp ?? []}
                onChange={(value) => updateFromForm({ ...fm, mcp: value }, body)}
                placeholder="Connect MCP servers…"
                emptyLabel="No matching servers"
              />
            </Field>
          </div>

          <div className="min-w-0 p-4 sm:p-5">
            <Field
              label="Skills"
              hint={`${(fm.skills ?? []).length} selected of ${extraSkillOptions.length}. Assigned skills preload; all others remain on demand.`}
            >
              <MultiSelect
                ariaLabel="Skills"
                options={extraSkillOptions}
                value={fm.skills ?? []}
                onChange={(value) => updateFromForm({ ...fm, skills: value }, body)}
                placeholder="Add skills…"
              />
            </Field>
          </div>
        </div>
      </AgentSection>

      <AgentSection
        icon={FileText}
        title={hasBuiltInProfile ? 'Extra instructions' : 'System instructions'}
        description={
          hasBuiltInProfile
            ? 'Appended after the versioned built-in prompt.'
            : 'Placed at the start of every conversation with this agent.'
        }
        meta={`${promptWordCount} words · ${body.length} chars`}
      >
        <div className="p-3 sm:p-4">
          <Textarea
            aria-label={hasBuiltInProfile ? 'Extra instructions' : 'System instructions'}
            value={body}
            onChange={(event) => updateFromForm(fm, event.target.value)}
            disabled={disabled}
            rows={16}
            placeholder="Define the agent's responsibility, constraints, workflow, and output style…"
            className="min-h-80 resize-y border-0 bg-(--bg-input) p-4 font-mono text-[13px] leading-[1.7] shadow-inner focus-visible:ring-2"
          />
        </div>
      </AgentSection>
    </div>
  )
}

function isBuiltInProfile(
  name?: string,
  role?: string | null,
  agentPath?: string,
): boolean {
  if (!name || !role) return false
  const path = agentPath ?? name
  return isBuiltInAgentName(path, role)
}

// ── Model picker ────────────────────────────────────────────────────────────

export function ModelCombobox({
  value,
  onChange,
  options,
  disabled,
  invalid,
  allowUnset,
  placeholder,
  unsetLabel = 'No model',
}: {
  value: string
  onChange: (v: string) => void
  options: ModelOption[]
  disabled?: boolean
  invalid?: boolean
  allowUnset?: boolean
  placeholder?: string
  unsetLabel?: string
}) {
  const [open, setOpen] = useState(false)
  const selected = options.find((option) => option.id === value)
  const provider = selected ? providerOf(selected.id) : ''
  const emptyLabel =
    placeholder ?? (allowUnset ? unsetLabel : 'Choose a model')

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            disabled={disabled}
            aria-label={`${allowUnset ? 'Fallback model' : 'Model'}: ${
              selected?.id ?? emptyLabel
            }`}
            aria-invalid={invalid || undefined}
            className={cn(
              'flex min-h-11 w-full items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-input) px-3 text-left text-sm outline-none transition-colors md:min-h-9',
              'hover:border-(--color-border-strong) focus-visible:border-(--focus-ring) focus-visible:ring-3 focus-visible:ring-(--focus-ring)/50',
              'aria-expanded:border-(--focus-ring) disabled:cursor-not-allowed disabled:opacity-50',
              invalid && 'border-(--color-error)',
            )}
          />
        }
      >
        {selected ? (
          <>
            <ProviderBrandIcon providerId={selected.id} size="xs" />
            <span className="min-w-0 flex-1 truncate font-medium text-(--color-text)">
              {shortModelName(selected.id)}
            </span>
            {provider && (
              <span className="shrink-0 font-mono text-[10px] tracking-wide text-(--color-text-subtle) uppercase">
                {provider}
              </span>
            )}
          </>
        ) : (
          <span className="min-w-0 flex-1 truncate text-(--color-text-muted)">
            {emptyLabel}
          </span>
        )}
        <ChevronDown
          size={14}
          aria-hidden="true"
          className={cn(
            'shrink-0 text-(--color-text-muted) transition-transform',
            open && 'rotate-180',
          )}
        />
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={4}
        className="w-[--anchor-width] min-w-72 max-w-[32rem] gap-0 p-2"
      >
        {allowUnset && (
          <button
            type="button"
            aria-pressed={!value}
            onClick={() => {
              onChange('')
              setOpen(false)
            }}
            className={cn(
              'mb-1 flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[11px] outline-none transition-colors',
              'hover:bg-(--bg-key) focus-visible:bg-(--bg-key)',
              !value
                ? 'bg-(--bg-key) text-(--color-text)'
                : 'text-(--color-text-2)',
            )}
          >
            <span className="min-w-0 flex-1 font-medium">{unsetLabel}</span>
            <Check
              aria-hidden="true"
              size={12}
              className={cn(
                'shrink-0 text-(--color-accent)',
                !value ? 'opacity-100' : 'opacity-0',
              )}
            />
          </button>
        )}
        <ModelOptions
          models={options}
          selectedModel={value}
          listClassName="max-h-64"
          onSelect={(modelId) => {
            onChange(modelId)
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

// ── Field wrapper ───────────────────────────────────────────────────────────

function AgentSection({
  icon: Icon,
  title,
  description,
  meta,
  children,
}: {
  icon: LucideIcon
  title: string
  description: string
  meta?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card) shadow-[0_1px_2px_rgba(15,23,42,0.03),0_12px_34px_rgba(15,23,42,0.025)]">
      <header className="flex items-start gap-3 border-b border-(--color-border-subtle) bg-(--bg-key)/25 px-4 py-3.5 sm:px-5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-(--color-border) bg-(--bg-card) text-(--color-text-muted)">
          <Icon size={14} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-heading text-sm font-semibold tracking-[-0.01em] text-(--color-text)">
            {title}
          </h2>
          <p className="mt-0.5 text-xs leading-relaxed text-(--color-text-muted)">
            {description}
          </p>
        </div>
        {meta && (
          <span className="shrink-0 rounded-full border border-(--color-border) bg-(--bg-card) px-2 py-1 font-mono text-[9px] tabular-nums text-(--color-text-subtle)">
            {meta}
          </span>
        )}
      </header>
      {children}
    </section>
  )
}

function CapabilityChips({ label, values }: { label: string; values: string[] }) {
  return (
    <details className="group rounded-lg border border-(--color-border) bg-(--bg-key)/35">
      <summary className="flex min-h-9 cursor-pointer list-none items-center gap-2 px-3 text-[11px] text-(--color-text-muted) outline-none transition-colors hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--focus-ring)/35 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1 truncate font-medium">{label}</span>
        <span className="rounded-full bg-(--bg-card) px-1.5 py-0.5 font-mono text-[9px] tabular-nums text-(--color-text-subtle) ring-1 ring-(--color-border)">
          {values.length}
        </span>
        <ChevronDown size={12} className="transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="max-h-40 overflow-y-auto border-t border-(--color-border-subtle) p-2.5">
        <div className="flex flex-wrap gap-1.5">
          {values.map((value) => (
            <span
              key={value}
              className="rounded-md bg-(--bg-card) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-2) ring-1 ring-(--color-border)"
            >
              {value}
            </span>
          ))}
        </div>
      </div>
    </details>
  )
}

function Field({
  label,
  required,
  className,
  children,
  error,
  hint,
}: {
  label: string
  required?: boolean
  className?: string
  children: React.ReactNode
  /** Zod-sourced error message. When set, rendered in destructive red
   *  under the control; when unset, the hint (if any) is rendered instead. */
  error?: string | null
  /** Helper text shown when there is no error. */
  hint?: string | null
}) {
  // Intentionally a <div>, not a <label>. A <label> wrapper would cause any
  // click inside it to activate the first focusable control in DOM order —
  // in MultiSelect that's the first chip's remove (×) button, which would
  // silently delete a chip when the user clicks empty space in the field.
  return (
    <div className={cn('flex min-w-0 flex-col gap-2', className)}>
      <span className="text-[11px] font-semibold tracking-[0.01em] text-(--color-text-2)">
        {label}
        {required && <span className="ml-0.5 text-(--color-error)">*</span>}
      </span>
      {children}
      {error ? (
        <p className="text-[11px] leading-relaxed text-(--color-error)">{error}</p>
      ) : hint ? (
        <p className="text-[11px] leading-relaxed text-(--color-text-muted)">{hint}</p>
      ) : null}
    </div>
  )
}

// ── Raw → form parser ───────────────────────────────────────────────────────

function parseFormState(raw: string): {
  fm: AgentFrontmatter
  body: string
  error: string | null
} {
  const { fm: fmText, body } = splitFrontmatter(raw)
  const fm: AgentFrontmatter = { name: '', role: 'member' }

  if (!fmText.trim()) {
    return { fm, body, error: 'Missing YAML frontmatter (needs --- … --- header).' }
  }

  try {
    const parsed = parseSimpleYaml(fmText)
    if (typeof parsed.name === 'string') fm.name = parsed.name
    if (parsed.role === 'lead' || parsed.role === 'member') fm.role = parsed.role
    if (typeof parsed.description === 'string') fm.description = parsed.description
    if (typeof parsed.model === 'string') fm.model = parsed.model
    if (typeof parsed.fallback_model === 'string') fm.fallback_model = parsed.fallback_model
    if (typeof parsed.thinking_level === 'string') fm.thinking_level = parsed.thinking_level
    if (typeof parsed.responses_api === 'boolean') fm.responses_api = parsed.responses_api
    if (Array.isArray(parsed.tools)) fm.tools = parsed.tools.filter((x) => typeof x === 'string')
    if (Array.isArray(parsed.tools_opt_out)) fm.tools_opt_out = parsed.tools_opt_out.filter((x) => typeof x === 'string')
    if (Array.isArray(parsed.skills)) fm.skills = parsed.skills.filter((x) => typeof x === 'string')
    if (Array.isArray(parsed.mcp)) fm.mcp = parsed.mcp.filter((x) => typeof x === 'string')
    return { fm, body, error: null }
  } catch (err) {
    return { fm, body, error: String((err as Error).message ?? err) }
  }
}

/**
 * Minimal YAML parser — handles the subset our AgentForm emits:
 * scalar key/values and bullet lists of strings. Anything more exotic
 * (nested objects, block scalars, anchors, flow style) is ignored
 * silently; the raw editor remains the escape hatch.
 */
function parseSimpleYaml(text: string): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  const lines = normalizeYamlScalarContinuations(text).split(/\r?\n/)
  let currentKey: string | null = null
  let currentList: string[] | null = null

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim() || line.trim().startsWith('#')) continue

    // List continuation
    const listMatch = /^\s+-\s+(.*)$/.exec(line)
    if (currentList && listMatch) {
      currentList.push(unquoteYamlScalar(listMatch[1]))
      continue
    }

    const kvMatch = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line)
    if (!kvMatch) {
      // Unknown indented content — skip gracefully.
      continue
    }
    const [, key, rawValue] = kvMatch
    currentKey = key
    currentList = null

    if (rawValue === '') {
      // Expect list on following lines.
      currentList = []
      out[currentKey] = currentList
      continue
    }
    out[currentKey] = coerce(unquoteYamlScalar(rawValue))
  }
  return out
}

function coerce(v: string): unknown {
  if (v === 'true') return true
  if (v === 'false') return false
  if (v === 'null' || v === '~' || v === '') return null
  const n = Number(v)
  if (!Number.isNaN(n) && v.trim() !== '') return n
  return v
}
