import type { AgentTool } from './tools'

export interface AgentDefinition {
  id: string
  name: string
  role: string
  goal: string
  backstory: string
  model: string
  provider: 'openai' | 'ollama'
  tools: string[]
  allowDelegation: boolean
  maxIterations: number
  systemPrompt?: string
}

export function buildAgentSystemPromptFromDef(agent: AgentDefinition, tools: AgentTool[]): string {
  const toolDescs = tools.map(t => `- ${t.name}: ${t.description}`).join('\n')

  return `You are ${agent.name}, a ${agent.role}.

Background: ${agent.backstory}

Your goal: ${agent.goal}

${agent.systemPrompt ? `Additional instructions: ${agent.systemPrompt}\n` : ''}
Available tools:
${toolDescs}

${agent.allowDelegation ? 'You CAN delegate tasks to other agents using delegate_work or ask_question.' : 'You CANNOT delegate tasks. Complete the work yourself.'}

Respond with:
Thought: <your reasoning>
Action:
\`\`\`json
{"tool": "<tool_name>", "args": {<params>}}
\`\`\`

When done:
Thought: <summary>
FINISH: <your result>`
}

export function createAgent(overrides: Partial<AgentDefinition> & { id: string; name: string; role: string }): AgentDefinition {
  return {
    goal: '',
    backstory: '',
    model: 'gpt-4o',
    provider: 'openai',
    tools: ['read_file', 'write_file'],
    allowDelegation: false,
    maxIterations: 10,
    ...overrides
  }
}
