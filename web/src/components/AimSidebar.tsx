/**
 * AimSidebar — AIM mode's navigation: mode switch (Forge|Coding|AIM),
 * the list of AIM projects, and each project's feature items rendered as
 * an expandable dropdown (aim-mode-shell-ux-spec.md v2.2 §3.1).
 *
 * Follows CodingSidebar's expand/active-row mechanics but stays much
 * smaller: AIM projects have a fixed set of five features, no free-form
 * workspace tree, and — deliberately — no per-day session list (per-run
 * sessions are numerous and auto-archived; runs live in each project's
 * Pipelines/Runs screens instead).
 */

import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  ArrowRightLeft,
  BookMarked,
  BookOpen,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Code2,
  Gauge,
  LayoutDashboard,
  Plus,
  Workflow,
} from 'lucide-react'
import { useAimProjectsQuery } from '@/queries/useAimProjectsQuery'
import { usePlatform } from '@/hooks/use-platform'
import { cn } from '@/lib/utils'
import type { LucideIcon } from 'lucide-react'

export type AimFeature = 'overview' | 'kb' | 'rulebook' | 'pipelines' | 'runs'

export const AIM_FEATURES: { key: AimFeature; label: string; Icon: LucideIcon }[] = [
  { key: 'overview', label: 'Overview', Icon: LayoutDashboard },
  { key: 'kb', label: 'Knowledge Base', Icon: BookOpen },
  { key: 'rulebook', label: 'Rulebook', Icon: BookMarked },
  { key: 'pipelines', label: 'Pipelines', Icon: Workflow },
  { key: 'runs', label: 'Runs & Reports', Icon: ClipboardList },
]

const LAST_AIM_PROJECT_KEY = 'oa-last-aim-project'

export function saveLastAimProject(projectId: string): void {
  try {
    localStorage.setItem(LAST_AIM_PROJECT_KEY, projectId)
  } catch {
    // ignore storage failures
  }
}

export function loadLastAimProject(): string | null {
  try {
    return localStorage.getItem(LAST_AIM_PROJECT_KEY)
  } catch {
    return null
  }
}

interface AimSidebarProps {
  activeProjectId?: string
  activeFeature?: AimFeature
  onNewProject: () => void
}

export function AimSidebar({ activeProjectId, activeFeature, onNewProject }: AimSidebarProps) {
  const navigate = useNavigate()
  const { isMacOverlay } = usePlatform()
  const projectsQuery = useAimProjectsQuery()
  const projects = projectsQuery.data ?? []
  // The active project is always expanded; others remember their toggle.
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(activeProjectId ? [activeProjectId] : []),
  )

  const toggleProject = (projectId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(projectId)) next.delete(projectId)
      else next.add(projectId)
      return next
    })
  }

  return (
    <div className="flex h-full w-60 shrink-0 flex-col overflow-hidden p-1">
      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[10px] bg-(--bg-sidebar)/80 shadow-sm backdrop-blur-xl">
        {/* Mode switch */}
        <div className={`shrink-0 px-2 ${isMacOverlay ? 'pt-10' : 'pt-2'}`}>
          <div className="flex h-8 items-center rounded-md border border-(--color-border) bg-(--bg-page) p-0.5">
            <button
              type="button"
              onClick={() => navigate({ to: '/' })}
              className="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text)"
            >
              <Gauge size={12} aria-hidden="true" />
              Forge
            </button>
            <button
              type="button"
              onClick={() => navigate({ to: '/coding' })}
              className="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text)"
            >
              <Code2 size={12} aria-hidden="true" />
              Coding
            </button>
            <button
              type="button"
              onClick={() => {}}
              className="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] bg-(--bg-key) px-2 text-xs font-medium text-(--color-text) shadow-sm"
            >
              <ArrowRightLeft size={12} aria-hidden="true" />
              AIM
            </button>
          </div>
        </div>

        {/* Project list */}
        <nav aria-label="AIM projects" className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {projectsQuery.isLoading ? (
            <p className="px-2 py-1.5 text-xs text-(--color-text-subtle)">Loading projects…</p>
          ) : projects.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-(--color-text-subtle)">
              No migration projects yet.
            </p>
          ) : (
            <div className="space-y-0.5">
              {projects.map((project) => {
                const isActive = project.id === activeProjectId
                const isExpanded = isActive || expanded.has(project.id)
                const rulebook = (
                  project.settings?.aim as { rulebook?: { id?: string } } | undefined
                )?.rulebook
                return (
                  <div key={project.id}>
                    <button
                      type="button"
                      onClick={() => {
                        if (!isActive) {
                          saveLastAimProject(project.id)
                          navigate({
                            to: '/aim/$projectId/$feature',
                            params: { projectId: project.id, feature: 'overview' },
                          })
                        } else {
                          toggleProject(project.id)
                        }
                      }}
                      className={cn(
                        'flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
                        isActive
                          ? 'bg-(--bg-key) font-medium text-(--color-text)'
                          : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
                      )}
                      title={rulebook?.id ? `${project.name} · ${rulebook.id}` : project.name}
                    >
                      {isExpanded ? (
                        <ChevronDown size={12} className="shrink-0 text-(--color-text-subtle)" />
                      ) : (
                        <ChevronRight size={12} className="shrink-0 text-(--color-text-subtle)" />
                      )}
                      <span className="min-w-0 flex-1 truncate">{project.name}</span>
                    </button>
                    {isExpanded && (
                      <div className="ml-3 space-y-0.5 border-l border-(--color-border) pl-2 pt-0.5">
                        {AIM_FEATURES.map(({ key, label, Icon }) => (
                          <button
                            key={key}
                            type="button"
                            onClick={() => {
                              saveLastAimProject(project.id)
                              navigate({
                                to: '/aim/$projectId/$feature',
                                params: { projectId: project.id, feature: key },
                              })
                            }}
                            className={cn(
                              'flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs transition-colors',
                              isActive && activeFeature === key
                                ? 'bg-(--bg-key) text-(--color-accent)'
                                : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                            )}
                          >
                            <Icon size={12} className="shrink-0" aria-hidden="true" />
                            <span className="truncate">{label}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </nav>

        {/* New / Join */}
        <div className="shrink-0 border-t border-(--color-border) p-2">
          <button
            type="button"
            onClick={onNewProject}
            className="flex h-8 w-full items-center justify-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-page) text-xs font-medium text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <Plus size={13} aria-hidden="true" />
            New / Join project
          </button>
        </div>
      </div>
    </div>
  )
}
