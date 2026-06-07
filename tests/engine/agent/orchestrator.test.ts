import { describe, it, expect, beforeAll } from 'vitest'
import { createAgent, buildAgentSystemPromptFromDef } from '../../../src/engine/agent/agent-definition'
import { createTeamState, addMessage, setAgentOutput, addTaskResult, getAgentContext } from '../../../src/engine/agent/team-state'
import { parseLedgerResponse, detectStall, shouldReplan } from '../../../src/engine/agent/progress-ledger'
import { parsePlanResponse } from '../../../src/engine/agent/planning'

describe('AgentDefinition', () => {
  it('should create agent with defaults', () => {
    const agent = createAgent({ id: 'dev', name: 'Developer', role: 'Backend Engineer' })
    expect(agent.id).toBe('dev')
    expect(agent.model).toBe('gpt-4o')
    expect(agent.allowDelegation).toBe(false)
    expect(agent.maxIterations).toBe(10)
  })

  it('should override defaults', () => {
    const agent = createAgent({
      id: 'test', name: 'Tester', role: 'QA',
      model: 'gpt-4o-mini', allowDelegation: true, maxIterations: 20
    })
    expect(agent.model).toBe('gpt-4o-mini')
    expect(agent.allowDelegation).toBe(true)
    expect(agent.maxIterations).toBe(20)
  })

  it('should build system prompt', () => {
    const agent = createAgent({ id: 'dev', name: 'Dev', role: 'Engineer', goal: 'Build features', backstory: '10 years exp' })
    const prompt = buildAgentSystemPromptFromDef(agent, [])
    expect(prompt).toContain('Dev')
    expect(prompt).toContain('Engineer')
    expect(prompt).toContain('Build features')
    expect(prompt).toContain('10 years exp')
  })
})

describe('TeamSharedState', () => {
  it('should create initial state', () => {
    const state = createTeamState('Build API', 'Working code')
    expect(state.task).toBe('Build API')
    expect(state.expectedOutput).toBe('Working code')
    expect(state.status).toBe('planning')
    expect(state.currentRound).toBe(0)
    expect(state.messages).toHaveLength(0)
  })

  it('should add messages', () => {
    const state = createTeamState('task', 'output')
    addMessage(state, { from: 'orchestrator', to: 'dev', type: 'task', content: 'Build API' })
    expect(state.messages).toHaveLength(1)
    expect(state.messages[0].from).toBe('orchestrator')
    expect(state.messages[0].timestamp).toBeGreaterThan(0)
  })

  it('should set agent output', () => {
    const state = createTeamState('task', 'output')
    setAgentOutput(state, 'dev', 'API code here')
    expect(state.agentOutputs['dev']).toBe('API code here')
  })

  it('should add task result', () => {
    const state = createTeamState('task', 'output')
    addTaskResult(state, { agentId: 'dev', output: 'done', success: true, iterations: 3 })
    expect(state.taskResults).toHaveLength(1)
    expect(state.taskResults[0].success).toBe(true)
  })

  it('should get agent context', () => {
    const state = createTeamState('task', 'output')
    state.plan = 'Step 1: Build\nStep 2: Test'
    state.facts = ['Using Node.js']
    setAgentOutput(state, 'other', 'Some output from other agent')
    addMessage(state, { from: 'orchestrator', to: 'dev', type: 'task', content: 'Build it' })

    const ctx = getAgentContext(state, 'dev')
    expect(ctx).toContain('Plan:')
    expect(ctx).toContain('Facts:')
    expect(ctx).toContain('Using Node.js')
    expect(ctx).toContain('other')
  })
})

describe('ProgressLedger', () => {
  it('should parse valid ledger response', () => {
    const response = `{
      "is_request_satisfied": {"answer": false, "reason": "Not done"},
      "is_progress_being_made": {"answer": true, "reason": "Making progress"},
      "is_in_loop": {"answer": false, "reason": "No loop"},
      "next_speaker": {"answer": "dev", "reason": "Needs to code"},
      "instruction_or_question": {"answer": "Build the REST API"}
    }`
    const ledger = parseLedgerResponse(response)
    expect(ledger).not.toBeNull()
    expect(ledger!.isRequestSatisfied.answer).toBe(false)
    expect(ledger!.nextSpeaker.answer).toBe('dev')
    expect(ledger!.instructionOrQuestion.answer).toBe('Build the REST API')
  })

  it('should return null for invalid response', () => {
    expect(parseLedgerResponse('not json')).toBeNull()
    expect(parseLedgerResponse('')).toBeNull()
  })

  it('should detect stall', () => {
    const ledger = {
      isRequestSatisfied: { answer: false, reason: '' },
      isProgressBeingMade: { answer: false, reason: 'Stuck' },
      isInLoop: { answer: false, reason: '' },
      nextSpeaker: { answer: 'dev', reason: '' },
      instructionOrQuestion: { answer: '' }
    }
    expect(detectStall(ledger, 0)).toBe(1)
    expect(detectStall(ledger, 2)).toBe(3)
  })

  it('should not stall when progress is made', () => {
    const ledger = {
      isRequestSatisfied: { answer: false, reason: '' },
      isProgressBeingMade: { answer: true, reason: 'Progress' },
      isInLoop: { answer: false, reason: '' },
      nextSpeaker: { answer: 'dev', reason: '' },
      instructionOrQuestion: { answer: '' }
    }
    expect(detectStall(ledger, 2)).toBe(0)
  })

  it('should replan when stalls exceed max', () => {
    expect(shouldReplan(3, 3)).toBe(true)
    expect(shouldReplan(2, 3)).toBe(false)
    expect(shouldReplan(5, 3)).toBe(true)
  })
})

describe('Planning', () => {
  it('should parse plan response', () => {
    const response = `{
      "facts": ["Need REST API", "Using Express"],
      "steps": ["Design schema", "Implement endpoints", "Write tests"],
      "agent_assignments": [
        {"agent_id": "dev", "task": "Implement endpoints"},
        {"agent_id": "tester", "task": "Write tests"}
      ]
    }`
    const plan = parsePlanResponse(response)
    expect(plan).not.toBeNull()
    expect(plan!.facts).toHaveLength(2)
    expect(plan!.steps).toHaveLength(3)
    expect(plan!.agentAssignments).toHaveLength(2)
    expect(plan!.agentAssignments[0].agentId).toBe('dev')
  })

  it('should return null for invalid response', () => {
    expect(parsePlanResponse('not json')).toBeNull()
  })
})
