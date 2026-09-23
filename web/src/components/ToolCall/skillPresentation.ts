/**
 * Skill activation presentation.
 *
 * There is no skill tool: the agent activates a Skill by reading its
 * ``SKILL.md`` with the ordinary ``read`` tool, and the harness inserts the
 * same kind of ``read`` when the user types ``$skill-name``. A full read of a
 * file named ``SKILL.md`` — no ``limit`` and no ``offset`` other than 1 — is
 * therefore rendered as "Using skill <name>", where the name is the Skill's
 * directory. Mirrors ``full_read_path`` / ``is_skill_file_read`` in
 * ``app/agent/skills/activation.py``.
 */

const SKILL_FILE_NAME = 'SKILL.md'

export interface SkillCallPresentation {
  /** Skill name — the directory that holds ``SKILL.md``. */
  skillName: string
  completedLabel: string
  activityLabel: string
  headerTitle: string
  family: 'skill'
}

/** The skill a tool call activates, or ``null`` when it is not an activation. */
export function getSkillActivationName(
  toolName: string | undefined,
  args: string | undefined,
): string | null {
  if (toolName !== 'read' || !args) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(args)
  } catch {
    return null
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null
  const { path, offset, limit } = parsed as Record<string, unknown>
  if (typeof path !== 'string' || !path) return null
  if (limit !== undefined && limit !== null) return null
  if (offset !== undefined && offset !== null && offset !== 1) return null
  const parts = path.split(/[\\/]/).filter(Boolean)
  if (parts.length < 2 || parts.at(-1) !== SKILL_FILE_NAME) return null
  return parts.at(-2) ?? null
}

/** User-facing labels for a Skill activation, or ``null`` for any other call. */
export function getSkillCallPresentation(
  toolName: string | undefined,
  args: string | undefined,
): SkillCallPresentation | null {
  const skillName = getSkillActivationName(toolName, args)
  if (!skillName) return null
  return {
    skillName,
    completedLabel: 'Used skill',
    activityLabel: `Using skill ${skillName}`,
    headerTitle: skillName,
    family: 'skill',
  }
}
