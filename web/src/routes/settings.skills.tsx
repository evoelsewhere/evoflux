/**
 * /settings/skills — every discovered Skill, with an on/off switch per row.
 */
import { Sparkles } from 'lucide-react'
import { useMemo } from 'react'

import type { SkillSummary } from '@/api/types'
import { SettingsListView, type ListViewRow } from '@/components/settings/SettingsListView'
import { ManagedResourceProviderBadge } from '@/components/settings/ManagedResourceProviderBadge'
import {
  SKILL_SOURCE_LABEL,
  skillInvalidReason,
  skillStatusLabels,
} from '@/components/settings/skillFacts'
import { Switch } from '@/components/ui/switch'
import { useSetSkillEnabledMutation, useSkillFilesQuery } from '@/queries'
import { useSettingsParams } from '@/contexts/SettingsContext'
import { useActiveSkillDiscoveryScope } from '@/hooks/useActiveSkillDiscoveryScope'
import { useToastStore } from '@/stores/useToastStore'

export function SkillsListPage() {
  const skillScope = useActiveSkillDiscoveryScope()
  const { data, isLoading, isFetching, isError, error, refetch } =
    useSkillFilesQuery(skillScope)
  const enableMut = useSetSkillEnabledMutation(skillScope)
  const push = useToastStore((s) => s.push)
  const { name: selected } = useSettingsParams() as { name?: string }
  const pendingName = enableMut.isPending ? enableMut.variables?.name : undefined
  const setEnabled = enableMut.mutate

  const rows = useMemo<ListViewRow[]>(() => {
    const toggle = (skill: SkillSummary, enabled: boolean) => {
      setEnabled(
        { name: skill.name, enabled },
        {
          onError: (err) =>
            push({
              tone: 'error',
              title: `Could not ${enabled ? 'enable' : 'disable'} "${skill.name}"`,
              description: err instanceof Error ? err.message : String(err),
            }),
        },
      )
    }
    return (data?.skills ?? []).map((skill) => {
      const sourceLabel = SKILL_SOURCE_LABEL[skill.source] ?? skill.source
      return {
        key: skill.name,
        to: '/settings/skills/$name',
        params: { name: skill.name },
        active: selected === skill.name,
        title: skill.name,
        badge: skill.provider ? (
          <span className="flex min-w-0 items-center gap-1.5">
            <ManagedResourceProviderBadge provider={skill.provider} />
            <span className="hidden rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-muted) ring-1 ring-(--color-border) sm:inline-flex">
              {sourceLabel}
            </span>
          </span>
        ) : sourceLabel,
        description: [skill.description || 'No description', ...skillStatusLabels(skill)].join(
          ' · ',
        ),
        meta: skill.location,
        invalidReason: skillInvalidReason(skill),
        action: (
          <Switch
            checked={skill.enabled}
            onCheckedChange={(checked) => toggle(skill, checked)}
            disabled={pendingName === skill.name}
            aria-label={`${skill.enabled ? 'Disable' : 'Enable'} ${skill.name}`}
          />
        ),
      }
    })
  }, [data?.skills, setEnabled, pendingName, push, selected])

  return (
    <SettingsListView
      title="Skills"
      icon={Sparkles}
      lede="Skills are folders with a SKILL.md. The agent sees each enabled skill's name and description and reads SKILL.md when a task matches; type $skill-name to use one yourself."
      newTo="/settings/skills/new"
      newLabel="New skill"
      filterPlaceholder="Filter skills…"
      rows={rows}
      isLoading={isLoading}
      isFetching={isFetching}
      isError={isError}
      error={error}
      onRetry={() => void refetch()}
      emptyTitle="No skills yet"
      emptyBody="Create a skill, or add a folder with a SKILL.md to a project's .agents/skills or your user skills directory."
    />
  )
}
