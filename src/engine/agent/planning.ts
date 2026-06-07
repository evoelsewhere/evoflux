import type { AgentDefinition } from './agent-definition'
import type { TeamSharedState } from './team-state'

export interface Plan {
  facts: string[]
  steps: string[]
  agentAssignments: Array<{ agentId: string; task: string }>
}

export function buildPlanningPrompt(task: string, agents: AgentDefinition[]): string {
  const agentDescs = agents.map(a =>
    `- ${a.id} (${a.role}): ${a.goal}. Tools: ${a.tools.join(', ')}`
  ).join('\n')

  return `You are planning how to complete this task using a team of agents.

TASK: ${task}

AVAILABLE AGENTS:
${agentDescs}

Create a plan with:
1. Key facts/assumptions
2. Execution steps (ordered)
3. Agent assignment for each step

Respond in this EXACT JSON format:
{
  "facts": ["fact 1", "fact 2"],
  "steps": ["step 1: description", "step 2: description"],
  "agent_assignments": [
    {"agent_id": "<id>", "task": "<specific task description>"},
    {"agent_id": "<id>", "task": "<specific task description>"}
  ]
}

Only respond with the JSON object.`
}

export function buildReplanPrompt(state: TeamSharedState, agents: AgentDefinition[]): string {
  const failedResults = state.taskResults.filter(r => !r.success).map(r =>
    `- ${r.agentId}: ${r.output.substring(0, 300)}`
  ).join('\n')

  const completedResults = state.taskResults.filter(r => r.success).map(r =>
    `- ${r.agentId}: ${r.output.substring(0, 300)}`
  ).join('\n')

  return `The current plan is not working. Re-analyze and create a new plan.

TASK: ${state.task}
EXPECTED OUTPUT: ${state.expectedOutput}

CURRENT PLAN:
${state.plan}

COMPLETED:
${completedResults || 'None'}

FAILED/STALLED:
${failedResults || 'None'}

FACTS:
${state.facts.map(f => `- ${f}`).join('\n')}

AVAILABLE AGENTS: ${agents.map(a => `${a.id} (${a.role})`).join(', ')}

Create an UPDATED plan. Respond in JSON:
{
  "facts": ["updated facts"],
  "steps": ["new step 1", "new step 2"],
  "agent_assignments": [{"agent_id": "<id>", "task": "<task>"}]
}`
}

export function parsePlanResponse(response: string): Plan | null {
  try {
    const jsonMatch = response.match(/\{[\s\S]*\}/)
    if (!jsonMatch) return null
    const parsed = JSON.parse(jsonMatch[0])

    return {
      facts: Array.isArray(parsed.facts) ? parsed.facts.map(String) : [],
      steps: Array.isArray(parsed.steps) ? parsed.steps.map(String) : [],
      agentAssignments: Array.isArray(parsed.agent_assignments)
        ? parsed.agent_assignments.map((a: { agent_id: string; task: string }) => ({
            agentId: String(a.agent_id || ''),
            task: String(a.task || '')
          }))
        : []
    }
  } catch {
    return null
  }
}

export function buildTaskPromptForAgent(
  agent: AgentDefinition,
  assignment: string,
  state: TeamSharedState
): string {
  const parts: string[] = [assignment]

  if (state.facts.length > 0) {
    parts.push(`\nKnown facts:\n${state.facts.map(f => `- ${f}`).join('\n')}`)
  }

  const otherOutputs = Object.entries(state.agentOutputs)
    .filter(([id]) => id !== agent.id)
  if (otherOutputs.length > 0) {
    parts.push(`\nResults from other agents:\n${otherOutputs.map(([id, out]) => `[${id}]: ${out.substring(0, 1000)}`).join('\n')}`)
  }

  return parts.join('\n')
}
