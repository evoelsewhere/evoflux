export type SkillCallKind = 'load' | 'read-resource' | 'list' | 'unknown'

export interface SkillCallPresentation {
  kind: SkillCallKind
  completedLabel: string
  activityLabel: string
  headerTitle: string | null
  family: string
}

function stringField(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

/** Derive user-facing skill activity from the tool's explicit action. */
export function getSkillCallPresentation(
  args: string | undefined,
): SkillCallPresentation | null {
  if (!args) return null

  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(args) as Record<string, unknown>
  } catch {
    return null
  }

  const skillName = stringField(parsed.skill_name)
  const resourcePath = stringField(parsed.resource_path)
  // `load` is the backend default, so older calls may omit action entirely.
  const action = stringField(parsed.action) ?? (skillName ? 'load' : null)

  if (action === 'load') {
    return {
      kind: 'load',
      completedLabel: 'Loaded skill',
      activityLabel: skillName ? `Loading skill ${skillName}` : 'Loading skill',
      headerTitle: skillName,
      family: 'skill-load',
    }
  }

  if (action === 'read_resource') {
    const target = [skillName, resourcePath].filter(Boolean).join(' · ') || null
    return {
      kind: 'read-resource',
      completedLabel: 'Read skill resource',
      activityLabel: resourcePath
        ? `Reading skill resource ${resourcePath}`
        : 'Reading skill resource',
      headerTitle: target,
      family: 'skill-resource',
    }
  }

  if (action === 'list') {
    return {
      kind: 'list',
      completedLabel: 'Listed skills',
      activityLabel: 'Listing skills',
      headerTitle: null,
      family: 'skill-list',
    }
  }

  return {
    kind: 'unknown',
    completedLabel: 'Used skill tool',
    activityLabel: 'Using skill tool',
    headerTitle: skillName,
    family: 'skill',
  }
}
