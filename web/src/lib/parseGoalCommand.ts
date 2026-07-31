export type ParsedGoalCommand =
  | { kind: 'none' }
  | { kind: 'status' }
  | { kind: 'start'; objective: string }
  | { kind: 'budget'; tokenBudget: number | null }
  | { kind: 'budget_invalid' }
  | { kind: 'pause' }
  | { kind: 'resume' }
  | { kind: 'stop' }
  | { kind: 'invalid' }

export function parseGoalCommand(content: string): ParsedGoalCommand {
  const trimmed = content.trim()
  if (trimmed === '/goal' || trimmed === '/goal:status') return { kind: 'status' }
  if (trimmed.startsWith('/goal ')) {
    const objective = trimmed.slice('/goal '.length).trim()
    return objective ? { kind: 'start', objective } : { kind: 'status' }
  }
  if (!trimmed.startsWith('/goal:')) return { kind: 'none' }

  const rest = trimmed.slice('/goal:'.length)
  const match = rest.match(/^(\S+)\s*([\s\S]*)$/)
  if (!match) return { kind: 'invalid' }
  const subcommand = match[1]
  const args = match[2].trim()

  if (subcommand === 'budget') {
    if (args === 'none' || args === 'unlimited') {
      return { kind: 'budget', tokenBudget: null }
    }
    if (/^\d+$/.test(args) && Number(args) > 0) {
      return { kind: 'budget', tokenBudget: Number(args) }
    }
    return { kind: 'budget_invalid' }
  }

  if (args) return { kind: 'invalid' }
  if (subcommand === 'pause' || subcommand === 'resume' || subcommand === 'stop') {
    return { kind: subcommand }
  }
  return { kind: 'invalid' }
}
