export type MessageType = 'task' | 'result' | 'question' | 'delegation' | 'feedback' | 'plan'

export interface AgentMessage {
  from: string
  to: string
  type: MessageType
  content: string
  timestamp: number
}

export interface TaskResult {
  agentId: string
  output: string
  success: boolean
  iterations: number
}

export type OrchestratorStatus = 'planning' | 'executing' | 'reviewing' | 'completed' | 'failed'

export interface TeamSharedState {
  task: string
  plan: string
  facts: string[]
  agentOutputs: Record<string, string>
  taskResults: TaskResult[]
  messages: AgentMessage[]
  currentRound: number
  stallCount: number
  status: OrchestratorStatus
  expectedOutput: string
}

export function createTeamState(task: string, expectedOutput: string): TeamSharedState {
  return {
    task,
    plan: '',
    facts: [],
    agentOutputs: {},
    taskResults: [],
    messages: [],
    currentRound: 0,
    stallCount: 0,
    status: 'planning',
    expectedOutput
  }
}

export function addMessage(state: TeamSharedState, msg: Omit<AgentMessage, 'timestamp'>): void {
  state.messages.push({ ...msg, timestamp: Date.now() })
}

export function setAgentOutput(state: TeamSharedState, agentId: string, output: string): void {
  state.agentOutputs[agentId] = output
}

export function addTaskResult(state: TeamSharedState, result: TaskResult): void {
  state.taskResults.push(result)
}

export function getAgentContext(state: TeamSharedState, agentId: string): string {
  const parts: string[] = []

  if (state.plan) parts.push(`Plan:\n${state.plan}`)
  if (state.facts.length > 0) parts.push(`Facts:\n${state.facts.map(f => `- ${f}`).join('\n')}`)

  const otherOutputs = Object.entries(state.agentOutputs)
    .filter(([id]) => id !== agentId)
  if (otherOutputs.length > 0) {
    parts.push(`Other agent outputs:\n${otherOutputs.map(([id, out]) => `[${id}]: ${out.substring(0, 500)}`).join('\n')}`)
  }

  const recentMessages = state.messages
    .filter(m => m.to === agentId || m.from === agentId)
    .slice(-5)
  if (recentMessages.length > 0) {
    parts.push(`Recent messages:\n${recentMessages.map(m => `[${m.from}→${m.to}] ${m.content.substring(0, 200)}`).join('\n')}`)
  }

  return parts.join('\n\n')
}
