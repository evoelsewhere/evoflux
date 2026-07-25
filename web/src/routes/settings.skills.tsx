/**
 * /settings/skills — inline list of skill packs in the detail pane.
 */
import { Sparkles } from 'lucide-react'
import { useMemo } from 'react'

import { SettingsListView, type ListViewRow } from '@/components/settings/SettingsListView'
import { useSkillFilesQuery } from '@/queries'
import { useSettingsParams } from '@/contexts/SettingsContext'

export function SkillsListPage() {
  const { data, isLoading, isError } = useSkillFilesQuery()
  const { name: selected } = useSettingsParams() as { name?: string }

  const rows = useMemo<ListViewRow[]>(() => {
    const skills = data?.skills ?? []
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
      const title = slash === -1 ? s.name : s.name.replace('/', ':')
      const badge = slash === -1 ? undefined : 'sub-skill'
      return {
        key: s.name,
        to: '/settings/skills/$name',
        params: { name: s.name },
        active: selected === s.name,
        title,
        badge,
        description: [
          s.description || 'No description',
          s.built_in ? 'Built-in' : null,
          !s.editable ? 'Read-only' : null,
          s.source !== 'global-EvoFlux' ? s.source : null,
        ].filter(Boolean).join(' · '),
        meta: slash === -1 ? undefined : s.name,
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
  }, [data?.skills, selected])

  return (
    <SettingsListView
      title="Skills"
      icon={Sparkles}
      description="Reusable instruction packs any agent can load on demand. Flat skills and one-level sub-skills (shown as parent:sub) both live in .evoflux/skills/."
      newTo="/settings/skills/new"
      newLabel="New skill"
      filterPlaceholder="Filter skills…"
      rows={rows}
      isLoading={isLoading}
      isError={isError}
      emptyTitle="No skills yet"
      emptyBody="Skills are reusable instruction modules agents load on demand via the skill tool."
    />
  )
}
