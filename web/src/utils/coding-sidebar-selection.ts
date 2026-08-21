/** Resolve one visible Coding sidebar scope without keeping stale selections. */
export function resolveCodingSidebarSelection(
  options: readonly string[],
  active: string | null | undefined,
  selected: string | null,
): string | null {
  if (active && options.includes(active)) return active
  if (selected && options.includes(selected)) return selected
  return options[0] ?? null
}
