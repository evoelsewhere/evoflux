import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PlanApprovalPending } from '@/api/types'
import { PlanReviewPanel } from '@/components/PlanReviewPanel'
import { useTeamStore } from '@/stores/useTeamStore'

const api = vi.hoisted(() => ({
  replyPlanApproval: vi.fn(),
}))

vi.mock('@/api/client', () => api)

const pendingPlan: PlanApprovalPending = {
  requestId: 'req-1',
  sessionId: 'session-1',
  plan: '# Do the thing\n\nSome plan body.',
  steps: [
    { tool: 'write', args: {}, summary: 'Append a line', path: 'README.md', diff_stat: { additions: 1, deletions: 0 } },
  ],
}

beforeEach(() => {
  api.replyPlanApproval.mockReset()
  useTeamStore.setState({ sessionId: 'session-1', planApproval: pendingPlan })
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

describe('PlanReviewPanel', () => {
  it('renders header, scrollable content, and a footer action bar with all three controls', async () => {
    render(<PlanReviewPanel onQuoteComment={vi.fn()} onRevise={vi.fn()} />)

    expect(screen.getByText('Plan review')).toBeInTheDocument()
    expect(await screen.findByText('Do the thing')).toBeInTheDocument()

    // Footer is rendered as a genuine sibling element after the scrollable
    // content region (not hidden/absent) and carries all three actions —
    // this is the smoke check for BUG-008 (action bar must exist in the
    // same panel, not float away in a separately-positioned component).
    const rejectButton = screen.getByRole('button', { name: /reject/i })
    const reviseButton = screen.getByRole('button', { name: /revise/i })
    const acceptButton = screen.getByRole('button', { name: /accept & execute/i })
    const footer = rejectButton.closest('footer')
    expect(footer).not.toBeNull()
    expect(footer).toContainElement(reviseButton)
    expect(footer).toContainElement(acceptButton)
  })

  it('accepts the plan via the footer action bar', async () => {
    api.replyPlanApproval.mockResolvedValue(undefined)
    render(<PlanReviewPanel onQuoteComment={vi.fn()} onRevise={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: /accept & execute/i }))

    await waitFor(() => {
      expect(api.replyPlanApproval).toHaveBeenCalledWith('session-1', 'req-1', 'approved')
    })
    expect(useTeamStore.getState().planApproval).toBeNull()
  })

  it('rejects the plan via the footer action bar', async () => {
    api.replyPlanApproval.mockResolvedValue(undefined)
    render(<PlanReviewPanel onQuoteComment={vi.fn()} onRevise={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: /reject/i }))

    await waitFor(() => {
      expect(api.replyPlanApproval).toHaveBeenCalledWith('session-1', 'req-1', 'rejected')
    })
    expect(useTeamStore.getState().planApproval).toBeNull()
  })

  it('focuses the composer via onRevise when Revise is clicked', () => {
    const onRevise = vi.fn()
    render(<PlanReviewPanel onQuoteComment={vi.fn()} onRevise={onRevise} />)

    fireEvent.click(screen.getByRole('button', { name: /revise/i }))

    expect(onRevise).toHaveBeenCalledTimes(1)
    expect(api.replyPlanApproval).not.toHaveBeenCalled()
  })
})
