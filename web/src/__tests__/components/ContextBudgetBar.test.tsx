import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
        output={968}
        trigger={204_000}
        onCompact={onCompact}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Context 4% used/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Compact context' }))

    await waitFor(() => expect(onCompact).toHaveBeenCalledOnce())
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
