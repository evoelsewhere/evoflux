/**
 * /settings/skills — inline list of skill packs in the detail pane.
 */
import { Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'

import { SettingsListView, type ListViewRow } from '@/components/settings/SettingsListView'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { resolveSkillDetailMode } from '@/lib/skill-detail-mode'
import {
  hasAllSkillModes,
  skillAvailabilityLabel,
  type SkillModeFilter,
} from '@/lib/skill-modes'
import { useSkillFilesQuery } from '@/queries'
import { useSettingsParams } from '@/contexts/SettingsContext'
import { useActiveSkillDiscoveryScope } from '@/hooks/useActiveSkillDiscoveryScope'

const MODE_COLLISION_FILTER_TEXT =
  'Filter by Work, Coding, or AIM to inspect runtime policy'

export function SkillsListPage() {
  const skillScope = useActiveSkillDiscoveryScope()
  const { data, isLoading, isFetching, isError, error, refetch } =
    useSkillFilesQuery(skillScope)
  const { name: selected } = useSettingsParams() as { name?: string }
  const [modeFilter, setModeFilter] = useState<SkillModeFilter>('all')
  const allSkills = useMemo(() => data?.skills ?? [], [data?.skills])
  const counts = useMemo(
    () => ({
      all: allSkills.length,
      work: allSkills.filter((skill) => skill.modes.includes('work')).length,
      coding: allSkills.filter((skill) => skill.modes.includes('coding')).length,
      aim: allSkills.filter((skill) => skill.modes.includes('aim')).length,
      allModes: allSkills.filter((skill) => hasAllSkillModes(skill.modes)).length,
    }),
    [allSkills],
  )

  const rows = useMemo<ListViewRow[]>(() => {
    const skills = allSkills.filter((skill) => {
      if (modeFilter === 'all') return true
      if (modeFilter === 'all-modes') return hasAllSkillModes(skill.modes)
      return skill.modes.includes(modeFilter)
    })
    const flat = skills.filter((s) => !s.name.includes('/'))
    const nested = skills.filter((s) => s.name.includes('/'))
    const nestedByParent = new Map<string, typeof nested>()
    for (const skill of nested) {
      const [parent] = skill.name.split('/', 1)
      const group = nestedByParent.get(parent) ?? []
      group.push(skill)
      nestedByParent.set(parent, group)
    }

    const toRow = (s: (typeof skills)[number]): ListViewRow => {
      const slash = s.name.indexOf('/')
      const portableName = slash === -1 ? s.name : s.name.replace('/', ':')
      const title = s.display_name || portableName
      const modeCollision = s.diagnostics.some(
        (diagnostic) => diagnostic.code === 'mode-specific-collision',
      )
      const badge = modeCollision
        ? 'Mode-specific variants'
        : s.allow_implicit_invocation
          ? 'Auto-discoverable'
          : 'Hidden from catalog'
      const detailMode = resolveSkillDetailMode({
        valid: s.valid,
        modes: s.modes,
        modeFilter,
        workspaceScoped: Boolean(skillScope.workspaces?.length),
      })
      return {
        key: s.name,
        to: '/settings/skills/$name',
        params: { name: s.name },
        search: detailMode ? { mode: detailMode } : undefined,
        active: selected === s.name,
        title,
        badge,
        description: [
          s.description || 'No description',
          skillAvailabilityLabel(s.modes),
          `${s.resource_count} resource${s.resource_count === 1 ? '' : 's'}`,
          modeCollision ? MODE_COLLISION_FILTER_TEXT : null,
          !modeCollision && !s.user_invocable ? 'Manual invocation disabled' : null,
          s.built_in ? 'Built-in' : null,
          !s.editable ? 'Bundle read-only' : null,
          s.symlinked ? 'Symlink' : null,
          s.diagnostics.length > 0
            ? `${s.diagnostics.length} diagnostic${s.diagnostics.length === 1 ? '' : 's'}`
            : null,
          s.source !== 'global-EvoFlux' ? s.source : null,
        ].filter(Boolean).join(' · '),
        meta: title === portableName ? undefined : s.name,
        invalidReason: !s.valid ? (s.error ?? 'Invalid configuration') : undefined,
        trailing: (
          <span
            className="flex h-7 w-7 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)"
            aria-hidden="true"
          >
            <Sparkles size={13} />
          </span>
        ),
      }
    }

    const rows: ListViewRow[] = flat.map(toRow)
    for (const [parent, group] of [...nestedByParent.entries()].sort(([a], [b]) => a.localeCompare(b))) {
      rows.push({
        key: `group:${parent}`,
        kind: 'group',
        title: `${parent} sub-skills`,
      })
      rows.push(...group.sort((a, b) => a.name.localeCompare(b.name)).map(toRow))
    }
    return rows
  }, [allSkills, modeFilter, selected, skillScope])

  return (
    <SettingsListView
      title="Skills"
      icon={Sparkles}
      lede="Portable Agent Skills discovered from project, user, Claude, Codex, and EvoFlux roots. Metadata is cataloged; instructions and resources load only when activated."
      newTo="/settings/skills/new"
      newLabel="New skill"
      filterPlaceholder="Filter skills…"
      tabs={
        <SegmentedControl
          options={[
            { value: 'all', label: `All ${counts.all}` },
            { value: 'work', label: `Work ${counts.work}` },
            { value: 'coding', label: `Coding ${counts.coding}` },
            { value: 'aim', label: `AIM ${counts.aim}` },
            { value: 'all-modes', label: `All modes ${counts.allModes}` },
          ]}
          value={modeFilter}
          onChange={setModeFilter}
          layoutId="skills-mode-filter"
          ariaLabel="Filter skills by mode"
          className="max-w-full overflow-x-auto"
        />
      }
      rows={rows}
      isLoading={isLoading}
      isFetching={isFetching}
      isError={isError}
      error={error}
      onRetry={() => void refetch()}
      emptyTitle="No skills yet"
      emptyBody="Skills are reusable instruction modules agents load on demand via the skill tool."
    />
  )
}
