/**
 * AgentInfoPopover — capabilities + tools in a compact popover.
 *
 * Triggered by clicking an info button in the SessionPillsRow.
 * Displays the lead agent description, capability chips, and
 * tool list (with MCP server grouping). Uses a simple absolute-
 * positioned panel rather than a modal dialog.
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Wrench,
  ChevronDown,
  ImageIcon,
  FileText,
  Mic,
  Video,
  ArrowRight,
  Plug,
  Info,
} from 'lucide-react'
import { useTeamAgentsQuery } from '@/queries/useAgentsQuery'
import { useMcpServersQuery } from '@/queries/useMcpQuery'
import { useTeamStore } from '@/stores/useTeamStore'
import { useMotionPreset } from '@/lib/motion'
import { resolveAgentRole } from '@/lib/agent-roles'
import { AgentChip } from '@/components/ui/agent-chip'
import type {
  AgentInfo,
  AgentCapabilities as AgentCapabilitiesType,
  TeamAgentInfo,
} from '@/api/types'

// ── Shared sub-components (from the retired Session Settings modal) ──────────

interface CapabilityChip {
  key: string
  label: string
  icon: React.ComponentType<{ size?: number; className?: string }>
}

function CapabilityChips({ chips }: { chips: CapabilityChip[] }) {
  if (chips.length === 0) {
    return <span className="text-xs italic text-(--color-text-muted)">—</span>
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map(({ key, label, icon: Icon }) => (
        <span
          key={key}
          className="flex items-center gap-1 rounded-md bg-(--bg-key) px-2 py-0.5 text-xs text-(--color-text-2) ring-1 ring-(--color-border-strong)"
          title={label}
        >
          <Icon size={11} className="text-(--color-text-muted)" />
          {label}
        </span>
      ))}
    </div>
  )
}

function CapabilitiesSection({
  caps,
}: {
  caps: AgentCapabilitiesType
}) {
  const inputChips: CapabilityChip[] = [
    caps.input.vision && { key: 'vision', label: 'Vision', icon: ImageIcon },
    caps.input.document_text && { key: 'docs', label: 'Documents', icon: FileText },
    caps.input.audio && { key: 'audio-in', label: 'Audio', icon: Mic },
    caps.input.video && { key: 'video', label: 'Video', icon: Video },
  ].filter(Boolean) as CapabilityChip[]

  const outputChips: CapabilityChip[] = [
    caps.output.text && { key: 'text-out', label: 'Text', icon: FileText },
    caps.output.image && { key: 'image-out', label: 'Image', icon: ImageIcon },
    caps.output.audio && { key: 'audio-out', label: 'Audio', icon: Mic },
  ].filter(Boolean) as CapabilityChip[]

  if (inputChips.length === 0 && outputChips.length === 0) return null

  return (
    <div className="py-2">
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-(--color-text-muted)">
        Capabilities
      </h4>
      <div className="flex flex-wrap items-center gap-2">
        <CapabilityChips chips={inputChips} />
        {inputChips.length > 0 && outputChips.length > 0 && (
          <ArrowRight size={12} className="text-(--color-text-subtle)" aria-hidden />
        )}
        <CapabilityChips chips={outputChips} />
      </div>
    </div>
  )
}

// ── Tool row ─────────────────────────────────────────────────────────────────

function ToolRow({ name, description }: { name: string; description: string }) {
  const [open, setOpen] = useState(false)
  const hasDesc = description.trim().length > 0
  return (
    <div className="overflow-hidden rounded-md border border-(--color-border) bg-(--bg-page) transition-colors hover:border-(--color-border-strong)">
      <button
        onClick={() => hasDesc && setOpen((v) => !v)}
        className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-left ${hasDesc ? 'cursor-pointer' : 'cursor-default'}`}
      >
        <Wrench size={10} className="shrink-0 text-(--color-text-muted)" />
        <code className="flex-1 truncate font-mono text-xs font-medium text-(--color-text)">{name}</code>
        {hasDesc && (
          <ChevronDown
            size={10}
            className={`shrink-0 text-(--color-text-muted) transition-transform duration-(--motion-fast) ${open ? 'rotate-180' : ''}`}
          />
        )}
      </button>
      <AnimatePresence initial={false}>
        {open && hasDesc && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <p className="border-t border-(--color-border) px-2.5 py-1.5 text-xs leading-relaxed text-(--color-text-muted)">
              {description}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Tool grouping ────────────────────────────────────────────────────────────

interface ToolGroup {
  server: string | null
  tools: AgentInfo['tools']
}

function groupTools(
  tools: AgentInfo['tools'],
  mcpServers: string[],
): ToolGroup[] {
  const servers = [...mcpServers].sort((a, b) => b.length - a.length)
  const buckets = new Map<string, AgentInfo['tools']>(
    mcpServers.map((s) => [s, []]),
  )
  const builtins: AgentInfo['tools'] = []

  for (const tool of tools) {
    const owner = servers.find((s) => tool.name.startsWith(`mcp_${s}_`))
    if (owner) buckets.get(owner)!.push(tool)
    else builtins.push(tool)
  }

  const groups: ToolGroup[] = []
  if (builtins.length > 0) groups.push({ server: null, tools: builtins })
  for (const name of [...mcpServers].sort()) {
    groups.push({ server: name, tools: buckets.get(name) ?? [] })
  }
  return groups
}

function ToolGroupHeader({
  server,
  count,
  collapsed,
  onToggle,
  mcpStatus,
}: {
  server: string | null
  count: number
  collapsed: boolean
  onToggle: () => void
  mcpStatus?: string | null
}) {
  const label = server === null ? 'Built-in' : `MCP · ${server}`
  const statusTone =
    mcpStatus === 'ready'
      ? 'bg-(--color-success)'
      : mcpStatus === 'error'
        ? 'bg-(--color-error)'
        : mcpStatus === 'starting' || mcpStatus === 'auth_required'
          ? 'bg-(--color-accent)'
          : 'bg-(--color-text-subtle)'
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center gap-2 pt-2 pb-1 text-left transition-opacity hover:opacity-80"
    >
      {server !== null && <Plug size={10} className="shrink-0 text-(--color-text-muted)" aria-hidden />}
      <span className="text-xs font-semibold uppercase tracking-widest text-(--color-text-muted)">{label}</span>
      {server !== null && mcpStatus && (
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusTone}`}
          title={mcpStatus}
          aria-label={`MCP status: ${mcpStatus}`}
        />
      )}
      <span className="rounded-md bg-(--bg-key) px-1.5 py-0.5 text-xs text-(--color-text-muted)">{count}</span>
      <ChevronDown
        size={10}
        className={`ml-auto shrink-0 text-(--color-text-muted) transition-transform duration-(--motion-fast) ${
          collapsed ? '' : 'rotate-180'
        }`}
      />
    </button>
  )
}

// ── Main popover ─────────────────────────────────────────────────────────────

export interface AgentInfoPopoverProps {
  agentNames?: string[]
  workspace?: string | null
  sessionModel?: string | null
  /** Roster for the workspace team — 'aim' sessions have their own. */
  mode?: 'coding' | 'aim' | null
}

export function AgentInfoPopover({
  agentNames = [],
  workspace = null,
  mode = null,
}: AgentInfoPopoverProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const preset = useMotionPreset()

  const { data, isLoading } = useTeamAgentsQuery(workspace, open, mode)
  const mcpServersQuery = useMcpServersQuery(open)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const allAgents: TeamAgentInfo[] = data?.agents ?? []
  const byName = new Map(allAgents.map((a) => [a.name, a]))
  const display: TeamAgentInfo[] = (() => {
    if (agentNames.length === 0) return allAgents
    const ordered = agentNames.map((n) => byName.get(n)).filter(Boolean) as TeamAgentInfo[]
    return ordered.length > 0 ? ordered : allAgents
  })()

  const leadFromApi = allAgents.find((a) => a.is_lead)
  const leadName = display.length > 1 ? (leadFromApi?.name ?? display[0]?.name ?? null) : null
  const leadAgent = (leadName ? byName.get(leadName) : null) ?? display[0]

  const mcpServerStatuses = useMemo(
    () => new Map((mcpServersQuery.data?.servers ?? []).map((server) => [server.name, server])),
    [mcpServersQuery.data?.servers],
  )
  const agentStreams = useTeamStore((s) => s.agentStreams)

  const toolGroups = useMemo(
    () => (leadAgent ? groupTools(leadAgent.tools, leadAgent.mcp_servers ?? []) : []),
    [leadAgent],
  )

  // Built-in group collapsed by default; MCP groups open by default
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    () => new Set(['__builtin__']),
  )
  const toggleGroup = (key: string) =>
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex h-7 w-7 items-center justify-center rounded-[7px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-(--color-accent)/30 ${
          open
            ? 'bg-(--bg-key) text-(--color-text)'
            : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text-2)'
        }`}
        title="Agent info & tools"
        aria-expanded={open}
      >
        <Info size={13} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 4 * preset.distance, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4 * preset.distance, scale: 0.97 }}
            transition={preset.spring}
            className="absolute bottom-full right-0 z-(--z-modal) mb-2 max-h-[60vh] w-[min(22rem,calc(100vw-1rem))] overflow-y-auto rounded-lg border border-(--color-border) bg-(--color-surface) shadow-(--shadow-popover)"
          >
            {isLoading || !leadAgent ? (
              <div className="space-y-2 p-3">
                <div className="h-4 w-32 animate-pulse rounded-xs bg-(--bg-key)" />
                <div className="h-8 animate-pulse rounded-xs bg-(--bg-key)" />
                <div className="h-16 animate-pulse rounded-xs bg-(--bg-key)" />
              </div>
            ) : (
              <div className="p-3">
                {/* Lead agent description */}
                <div className="mb-2">
                  <h3 className="text-xs font-semibold text-(--color-text)">Lead agent</h3>
                  <p className="mt-0.5 text-xs leading-relaxed text-(--color-text-2)">
                    {leadAgent.description?.trim() || (
                      <span className="italic text-(--color-text-muted)">No description.</span>
                    )}
                  </p>
                </div>

                {/* Team roster */}
                {display.length > 1 && (
                  <div className="mb-2 border-t border-(--color-border) pt-2">
                    <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-(--color-text-muted)">
                      Team
                    </h4>
                    <div className="flex flex-col gap-1">
                      {display.map((member) => {
                        const status = agentStreams[member.name]?.status
                        return (
                          <div key={member.name} className="flex items-center gap-2">
                            <AgentChip
                              role={resolveAgentRole(member.name)}
                              label={member.name}
                              active={member.is_lead || status === 'working'}
                              className="min-w-0 flex-1 truncate px-2 py-1"
                              dotClassName={
                                status === 'error'
                                  ? 'bg-(--color-error)'
                                  : status === 'working'
                                    ? 'animate-pulse bg-(--color-accent)'
                                    : status === 'offline'
                                      ? 'bg-(--color-text-subtle) opacity-50'
                                      : undefined
                              }
                            />
                            {member.is_lead && (
                              <span className="shrink-0 text-[10px] text-(--color-accent)">lead</span>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Capabilities */}
                {leadAgent.capabilities && (
                  <CapabilitiesSection caps={leadAgent.capabilities} />
                )}

                {/* Tools */}
                {toolGroups.length > 0 && (
                  <div className="mt-2">
                    <h4 className="mb-1 text-xs font-semibold uppercase tracking-widest text-(--color-text-muted)">
                      Tools
                    </h4>
                    {toolGroups.map((group) => {
                      const key = group.server ?? '__builtin__'
                      const collapsed = collapsedGroups.has(key)
                      const mcpStatus = group.server
                        ? (mcpServerStatuses.get(group.server)?.state ?? null)
                        : null
                      return (
                        <div key={key} className="mb-1">
                          <ToolGroupHeader
                            server={group.server}
                            count={group.tools.length}
                            collapsed={collapsed}
                            onToggle={() => toggleGroup(key)}
                            mcpStatus={mcpStatus}
                          />
                          <AnimatePresence initial={false}>
                            {!collapsed && (
                              <motion.div
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: 'auto', opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                className="overflow-hidden"
                              >
                                <div className="flex flex-col gap-0.5 pt-0.5">
                                  {group.tools.map((tool) => (
                                    <ToolRow
                                      key={tool.name}
                                      name={tool.name}
                                      description={tool.description}
                                    />
                                  ))}
                                </div>
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
