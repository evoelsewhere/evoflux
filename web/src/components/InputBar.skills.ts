export interface SkillDirectiveRange {
  start: number
  end: number
  name: string
}

/**
 * Find committed ``/skill:<name>`` directives at the start of a line.
 *
 * Flat skills use ``/skill:release-audit`` while one-level sub-skills use the same
 * colon notation as the settings UI (for example ``/skill:git:commit``).
 * When ``skillNames`` is provided, unknown directives remain plain text.
 */
export function findSkillDirectives(
  text: string,
  skillNames?: ReadonlySet<string>,
): SkillDirectiveRange[] {
  const ranges: SkillDirectiveRange[] = []
  const pattern = /(^|\n)\/skill:([a-zA-Z0-9][a-zA-Z0-9._-]*(?::[a-zA-Z0-9][a-zA-Z0-9._-]*)?)(?=\s|$)/g

  for (const match of text.matchAll(pattern)) {
    const name = match[2]
    if (skillNames && !skillNames.has(name)) continue
    const start = (match.index ?? 0) + match[1].length
    ranges.push({ start, end: start + `/skill:${name}`.length, name })
  }

  return ranges
}
