import type { TeamSharedState } from './team-state'

export interface ProgressLedger {
  isRequestSatisfied: { answer: boolean; reason: string }
  isProgressBeingMade: { answer: boolean; reason: string }
  isInLoop: { answer: boolean; reason: string }
  nextSpeaker: { answer: string; reason: string }
  instructionOrQuestion: { answer: string }
}

export function createDefaultLedger(): ProgressLedger {
  return {
    isRequestSatisfied: { answer: false, reason: 'Not yet evaluated' },
    isProgressBeingMade: { answer: true, reason: 'Starting' },
    isInLoop: { answer: false, reason: 'Not yet evaluated' },
    nextSpeaker: { answer: '', reason: '' },
    instructionOrQuestion: { answer: '' }
  }
}

export function buildLedgerPrompt(state: TeamSharedState, agentIds: string[]): string {
  const recentResults = state.taskResults.slice(-5).map(r =>
    `- ${r.agentId}: ${r.success ? 'success' : 'failed'} — ${r.output.substring(0, 300)}`
  ).join('\n')

  return `You are a task orchestrator managing a team of agents.

TASK: ${state.task}
EXPECTED OUTPUT: ${state.expectedOutput}
CURRENT ROUND: ${state.currentRound}

PLAN:
${state.plan || 'No plan yet'}

FACTS:
${state.facts.map(f => `- ${f}`).join('\n') || 'None'}

RECENT RESULTS:
${recentResults || 'None'}

AVAILABLE AGENTS: ${agentIds.join(', ')}

Evaluate progress and respond in this EXACT JSON format:
{
  "is_request_satisfied": {"answer": true/false, "reason": "..."},
  "is_progress_being_made": {"answer": true/false, "reason": "..."},
  "is_in_loop": {"answer": true/false, "reason": "..."},
  "next_speaker": {"answer": "<agent_id>", "reason": "..."},
  "instruction_or_question": {"answer": "<what to tell the next agent>"}
}

Only respond with the JSON object.`
}

export function parseLedgerResponse(response: string): ProgressLedger | null {
  try {
    const jsonMatch = response.match(/\{[\s\S]*\}/)
    if (!jsonMatch) return null
    const parsed = JSON.parse(jsonMatch[0])

    return {
      isRequestSatisfied: {
        answer: Boolean(parsed.is_request_satisfied?.answer),
        reason: String(parsed.is_request_satisfied?.reason || '')
      },
      isProgressBeingMade: {
        answer: Boolean(parsed.is_progress_being_made?.answer ?? true),
        reason: String(parsed.is_progress_being_made?.reason || '')
      },
      isInLoop: {
        answer: Boolean(parsed.is_in_loop?.answer),
        reason: String(parsed.is_in_loop?.reason || '')
      },
      nextSpeaker: {
        answer: String(parsed.next_speaker?.answer || ''),
        reason: String(parsed.next_speaker?.reason || '')
      },
      instructionOrQuestion: {
        answer: String(parsed.instruction_or_question?.answer || '')
      }
    }
  } catch {
    return null
  }
}

export function detectStall(ledger: ProgressLedger, currentStallCount: number): number {
  if (!ledger.isProgressBeingMade.answer || ledger.isInLoop.answer) {
    return currentStallCount + 1
  }
  return 0
}

export function shouldReplan(stallCount: number, maxStalls: number): boolean {
  return stallCount >= maxStalls
}
