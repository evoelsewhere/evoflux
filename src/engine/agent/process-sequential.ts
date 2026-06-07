import type { AgentDefinition } from './agent-definition'
import type { TeamSharedState, TaskResult } from './team-state'
import { setAgentOutput, addTaskResult, addMessage } from './team-state'
import { buildAgentSystemPromptFromDef } from './agent-definition'
import { getTool, type AgentTool } from './tools'
import { parseAgentOutput, buildToolResultPrompt } from './parser'
import { AgentError } from '../errors'

export interface SequentialResult {
  success: boolean
  output: string
  results: TaskResult[]
}

export async function runSequential(
  agents: AgentDefinition[],
  state: TeamSharedState,
  signal?: AbortSignal
): Promise<SequentialResult> {
  const results: TaskResult[] = []
  let previousOutput = ''

  for (const agent of agents) {
    if (signal?.aborted) throw new AgentError('Aborted')

    const tools = agent.tools.map(name => getTool(name)).filter((t): t is AgentTool => t !== undefined)
    const systemPrompt = buildAgentSystemPromptFromDef(agent, tools)

    let context = state.task
    if (previousOutput) {
      context = `Previous agent output:\n${previousOutput}\n\nYour task: ${state.task}`
    }

    const messages: Array<{ role: string; content: string }> = [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: context }
    ]

    addMessage(state, { from: 'orchestrator', to: agent.id, type: 'task', content: context })

    let finalOutput = ''
    let iterations = 0

    for (let i = 0; i < agent.maxIterations; i++) {
      if (signal?.aborted) throw new AgentError('Aborted')
      iterations++

      let llmOutput: string
      try {
        llmOutput = await window.api.ai.chat(messages, { model: agent.model, provider: agent.provider })
      } catch (error) {
        const msg = error instanceof Error ? error.message : 'LLM failed'
        const result: TaskResult = { agentId: agent.id, output: `Error: ${msg}`, success: false, iterations }
        addTaskResult(state, result)
        results.push(result)
        break
      }

      const parsed = parseAgentOutput(llmOutput)

      if (parsed.type === 'finish') {
        finalOutput = parsed.finalAnswer || parsed.thought
        break
      }

      if (parsed.type === 'tool_call' && parsed.toolName) {
        messages.push({ role: 'assistant', content: llmOutput })
        const tool = getTool(parsed.toolName)
        let toolResult = `Tool '${parsed.toolName}' not found`
        if (tool?.handlerFn) {
          try {
            toolResult = await tool.handlerFn(parsed.toolArgs || {}, { pool: undefined as never, nodeId: agent.id, signal })
          } catch (e) {
            toolResult = `Error: ${e instanceof Error ? e.message : 'Tool failed'}`
          }
        }
        messages.push({ role: 'user', content: buildToolResultPrompt(parsed.toolName, toolResult) })
        continue
      }

      messages.push({ role: 'assistant', content: llmOutput })
      messages.push({ role: 'user', content: 'Please use a tool or FINISH.' })
    }

    if (!finalOutput) finalOutput = 'Agent did not produce a final answer.'

    const result: TaskResult = { agentId: agent.id, output: finalOutput, success: !!finalOutput && finalOutput !== 'Agent did not produce a final answer.', iterations }
    addTaskResult(state, result)
    setAgentOutput(state, agent.id, finalOutput)
    addMessage(state, { from: agent.id, to: 'orchestrator', type: 'result', content: finalOutput })
    results.push(result)
    previousOutput = finalOutput
  }

  return {
    success: results.every(r => r.success),
    output: previousOutput,
    results
  }
}
