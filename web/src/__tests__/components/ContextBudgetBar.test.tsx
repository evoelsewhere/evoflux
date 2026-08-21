import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ContextBudgetBar } from '@/components/ContextBudgetBar'

describe('ContextBudgetBar manual compaction', () => {
  it('lets the user trigger context compaction from the usage popover', async () => {
    const onCompact = vi.fn().mockResolvedValue(undefined)
    render(
      <ContextBudgetBar
        used={12_100}
        max={272_000}
        input={12_100}
        turnInput={17_000}
        turnOutput={968}
        turnCalls={3}
        trigger={204_000}
        onCompact={onCompact}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Context 4% used/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Compact context' }))

    await waitFor(() => expect(onCompact).toHaveBeenCalledOnce())
  })

  it('separates the latest main context from aggregate turn usage', async () => {
    render(
      <ContextBudgetBar
        used={14_200}
        max={272_000}
        input={14_200}
        cached={2_000}
        turnInput={17_000}
        turnOutput={17}
        turnCached={2_500}
        turnCalls={3}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Context 5% used/ }))

    const current = await screen.findByRole('heading', { name: 'Current context' })
    const currentSection = current.closest('section')
    expect(currentSection).not.toBeNull()
    expect(within(currentSection as HTMLElement).getByText('12.2K')).toBeInTheDocument()
    expect(within(currentSection as HTMLElement).getByText('2K')).toBeInTheDocument()

    const turn = screen.getByRole('heading', { name: 'Turn usage' })
    const turnSection = turn.closest('section')
    expect(turnSection).not.toBeNull()
    expect(within(turnSection as HTMLElement).getByText('17K')).toBeInTheDocument()
    expect(within(turnSection as HTMLElement).getByText('17')).toBeInTheDocument()
    expect(within(turnSection as HTMLElement).getByText('2.5K')).toBeInTheDocument()
    expect(within(turnSection as HTMLElement).getByText('3 model calls')).toBeInTheDocument()
  })

  it('disables manual compaction while the session is working', async () => {
    const onCompact = vi.fn()
    render(
      <ContextBudgetBar
        used={12_100}
        max={272_000}
        onCompact={onCompact}
        compactDisabled
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Context 4% used/ }))
    const compactButton = await screen.findByRole('button', { name: 'Compact context' })

    expect(compactButton).toBeDisabled()
    fireEvent.click(compactButton)
    expect(onCompact).not.toHaveBeenCalled()
  })
})
