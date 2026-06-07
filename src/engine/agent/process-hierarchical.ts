import type { AgentDefinition } from './agent-definition'
import type { TeamSharedState, TaskResult } from './team-state'
import { setAgentOutput, addTaskResult, addMessage, getAgentContext } from './team-state'
import { buildAgentSystemPromptFromDef } from './agent-definition'
import { getTool, type AgentTool } from './tools'
import { parseAgentOutput, buildToolResultPrompt } from './parser'
import { type ProgressLedger, buildLedgerPrompt, parseLedgerResponse, detectStall, shouldReplan } from './progress-ledger'
import { buildPlanningPrompt, buildReplanPrompt, buildTaskPromptForAgent, parsePlanResponse } from './planning'
import { AgentError } from '../errors'

export interface HierarchicalConfig {
  managerModel: string
  managerProvider: 'openai' | 'ollama'
  maxRounds: number
  maxStalls: number
  planning: boolean
}

export interface HierarchicalResult {
  success: boolean
  output: string
  results: TaskResult[]
  rounds: number
}

export async function runHierarchical(
  agents: AgentDefinition[],
  state: TeamSharedState,
  config: HierarchicalConfig,
  signal?: AbortSignal
): Promise<HierarchicalResult> {
  const agentMap = new Map(agents.map(a => [a.id, a]))
  const agentIds = agents.map(a => a.id)
  const results: TaskResult[] = []

  // Phase 1: Planning
  if (config.planning) {
    state.status = 'planning'
    const planPrompt = buildPlanningPrompt(state.task, agents)
    try {
      const planResponse = await window.api.ai.chat(
        [{ role: 'user', content: planPrompt }],
        { model: config.managerModel, provider: config.managerProvider }
      )
      const plan = parsePlanResponse(planResponse)
      if (plan) {
        state.plan = plan.steps.join('\n')
        state.facts = plan.facts
      }
    } catch {
      // Planning failed, continue without plan
    }
  }

  // Phase 2: Execution
  state.status = 'executing'

  for (let round = 0; round < config.maxRounds; round++) {
    if (signal?.aborted) throw new AgentError('Aborted')

    state.currentRound = round

    // Evaluate progress ledger
    const ledgerPrompt = buildLedgerPrompt(state, agentIds)
    let ledger: ProgressLedger | null = null
    try {
      const ledgerResponse = await window.api.ai.chat(
        [{ role: 'user', content: ledgerPrompt }],
        { model: config.managerModel, provider: config.managerProvider }
      )
      ledger = parseLedgerResponse(ledgerResponse)
    } catch {
      // Ledger evaluation failed
    }

    if (!ledger) {
      ledger = {
        isRequestSatisfied: { answer: false, reason: 'Ledger eval failed' },
        isProgressBeingMade: { answer: true, reason: 'Continuing' },
        isInLoop: { answer: false, reason: '' },
        nextSpeaker: { answer: agentIds[round % agentIds.length], reason: 'Round-robin' },
        instructionOrQuestion: { answer: state.task }
      }
    }

    // Check completion
    if (ledger.isRequestSatisfied.answer) {
      state.status = 'completed'
      const lastOutput = Object.values(state.agentOutputs).pop() || ''
      return { success: true, output: lastOutput, results, rounds: round }
    }

    // Stall detection
    state.stallCount = detectStall(ledger, state.stallCount)

    if (shouldReplan(state.stallCount, config.maxStalls)) {
      state.stallCount = 0
      try {
        const replanPrompt = buildReplanPrompt(state, agents)
        const replanResponse = await window.api.ai.chat(
          [{ role: 'user', content: replanPrompt }],
          { model: config.managerModel, provider: config.managerProvider }
        )
        const newPlan = parsePlanResponse(replanResponse)
        if (newPlan) {
          state.plan = newPlan.steps.join('\n')
          state.facts = newPlan.facts
        }
      } catch {
        // Re-planning failed
      }
      continue
    }

    // Execute next agent
    const nextAgentId = ledger.nextSpeaker.answer
    const agent = agentMap.get(nextAgentId)

    if (!agent) {
      // Fallback: pick first agent
      const fallback = agents[0]
      if (!fallback) throw new AgentError('No agents available')
      await executeAgent(fallback, ledger.instructionOrQuestion.answer, state, results, signal)
    } else {
      await executeAgent(agent, ledger.instructionOrQuestion.answer, state, results, signal)
    }
  }

  state.status = 'failed'
  const lastOutput = Object.values(state.agentOutputs).pop() || 'Max rounds reached'
  return { success: false, output: lastOutput, results, rounds: config.maxRounds }
}

async function executeAgent(
  agent: AgentDefinition,
  instruction: string,
  state: TeamSharedState,
  results: TaskResult[],
  signal?: AbortSignal
): Promise<void> {
  const tools = agent.tools.map(name => getTool(name)).filter((t): t is AgentTool => t !== undefined)
  const systemPrompt = buildAgentSystemPromptFromDef(agent, tools)
  const agentContext = getAgentContext(state, agent.id)
  const taskPrompt = buildTaskPromptForAgent(agent, instruction || state.task, state)

  const messages: Array<{ role: string; content: string }> = [
    { role: 'system', content: systemPrompt }
  ]
  if (agentContext) {
    messages.push({ role: 'system', content: `Team context:\n${agentContext}` })
  }
  messages.push({ role: 'user', content: taskPrompt })

  addMessage(state, { from: 'orchestrator', to: agent.id, type: 'task', content: instruction })

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
      return
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

  const result: TaskResult = { agentId: agent.id, output: finalOutput, success: true, iterations }
  addTaskResult(state, result)
  setAgentOutput(state, agent.id, finalOutput)
  addMessage(state, { from: agent.id, to: 'orchestrator', type: 'result', content: finalOutput })
  results.push(result)
}
