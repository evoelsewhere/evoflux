import { describe, expect, it } from 'vitest'
import { workflowProgressExecutionId } from './aim-workflow-events'

describe('AIM workflow progress events', () => {
  it('returns the execution id from workflow progress', () => {
    expect(
      workflowProgressExecutionId('workflow_progress', {
        execution_id: '019c1234-0000-7000-8000-000000000001',
        status: 'waiting_gate',
      }),
    ).toBe('019c1234-0000-7000-8000-000000000001')
  })

  it('ignores unrelated or malformed stream events', () => {
    expect(workflowProgressExecutionId('message_chunk', { execution_id: 'other' })).toBeNull()
    expect(workflowProgressExecutionId('workflow_progress', null)).toBeNull()
    expect(workflowProgressExecutionId('workflow_progress', { execution_id: 42 })).toBeNull()
  })
})
