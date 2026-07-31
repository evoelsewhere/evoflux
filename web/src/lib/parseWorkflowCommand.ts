/**
 * /workflow <name> [arg1 arg2 …] — FE-intercepted (plan v5 §9.1, F17):
 * the raw slash text is NEVER sent as a chat message; the FE
 * maps positional args onto declared inputs and calls the run endpoint.
 */

export type ParsedWorkflowCommand =
  | { kind: 'none' }
  | { kind: 'missing_name' }
  | { kind: 'run'; name: string; args: string[] }

export function parseWorkflowCommand(content: string): ParsedWorkflowCommand {
  const trimmed = content.trim()
  if (trimmed === '/workflow') return { kind: 'missing_name' }
  if (!trimmed.startsWith('/workflow ')) return { kind: 'none' }
  const rest = trimmed.slice('/workflow '.length).trim()
  if (!rest) return { kind: 'missing_name' }
  const [name, ...args] = rest.split(/\s+/)
  return { kind: 'run', name, args }
}

/** Map positional args onto declared inputs, coerced by type. Returns the
 * values plus which required inputs are still missing (→ open the dialog). */
export function mapWorkflowArgs(
  inputs: Array<{
    name: string
    type: string
    required: boolean
    default?: unknown
    options?: string[] | null
  }>,
  args: string[],
): { values: Record<string, unknown>; missing: string[]; errors: string[] } {
  const values: Record<string, unknown> = {}
  const errors: string[] = []
  inputs.forEach((spec, index) => {
    const raw = args[index]
    if (raw === undefined) return
    if (spec.type === 'number') {
      const parsed = Number(raw)
      if (Number.isNaN(parsed)) errors.push(`${spec.name}: '${raw}' is not a number`)
      else values[spec.name] = parsed
    } else if (spec.type === 'boolean') {
      values[spec.name] = ['1', 'true', 'yes'].includes(raw.toLowerCase())
    } else if (spec.type === 'enum') {
      if (spec.options && !spec.options.includes(raw)) {
        errors.push(`${spec.name}: '${raw}' not in ${spec.options.join('|')}`)
      } else {
        values[spec.name] = raw
      }
    } else {
      values[spec.name] = raw
    }
  })
  const missing = inputs
    .filter(
      (spec) =>
        spec.required && values[spec.name] === undefined && spec.default == null,
    )
    .map((spec) => spec.name)
  return { values, missing, errors }
}
