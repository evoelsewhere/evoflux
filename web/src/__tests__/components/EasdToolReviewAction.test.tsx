import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import {
  EasdToolReviewAction,
} from '@/components/easd/EasdToolReviewAction'
import { easdToolReviewTarget } from '@/components/easd/easdToolReviewTarget'
import { useUIStore } from '@/stores/useUIStore'

describe('EASD successful tool review action', () => {
  beforeEach(() => {
    useUIStore.setState({ easdRunOpenRequest: null, easdSelectedRunId: null })
  })

  it('parses successful Spec and Plan submissions but ignores failures', () => {
    expect(easdToolReviewTarget(
      'easd_submit_specification',
      JSON.stringify({ run_id: 'run-spec' }),
      'Specification draft persisted for user review. revision=rev-1 hash=abc.',
    )).toEqual({ runId: 'run-spec', label: 'Review specification' })
    expect(easdToolReviewTarget(
      'easd_submit_plan',
      JSON.stringify({ run_id: 'run-plan' }),
      'Plan draft persisted for user review. revision=plan-1 hash=def.',
    )).toEqual({ runId: 'run-plan', label: 'Review plan' })
    expect(easdToolReviewTarget(
      'easd_submit_specification',
      JSON.stringify({ run_id: 'run-spec' }),
      'Error: invalid verification command',
    )).toBeNull()
    expect(easdToolReviewTarget(
      'easd_submit_plan',
      '{not-json',
      'Plan draft persisted for user review.',
    )).toBeNull()
  })

  it('opens the exact EASD Run from the review button', () => {
    render(<EasdToolReviewAction target={{ runId: 'run-7', label: 'Review specification' }} />)

    fireEvent.click(screen.getByRole('button', { name: 'Review specification' }))

    expect(useUIStore.getState().easdRunOpenRequest).toMatchObject({ runId: 'run-7' })
    expect(useUIStore.getState().activeWorkbenchTool).toBe('easd')
  })
})
