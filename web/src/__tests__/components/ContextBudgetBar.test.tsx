import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import { ContextBudgetBar } from '@/components/ContextBudgetBar'

vi.mock('@/api/client', () => ({
  // The threshold control fetches the global setting when the popover opens.
  getContextSettings: vi.fn().mockResolvedValue({
    summary_trigger_tokens: null,
    summary_max_tokens: null,
    keep_recent_turns: null,
    tool_result_offload_chars: null,
    keep_recent_tool_batches: null,
    defaults: {
      summary_trigger_tokens: 334_000,
      summary_max_tokens: 30_000,
      keep_recent_turns: 3,
      tool_result_offload_chars: 40_000,
      keep_recent_tool_batches: 4,
    },
    max_tokens: 750_000,
  }),
  updateContextSettings: vi.fn(),
}))

/** The popover reads the shared query cache, so it needs a provider. */
function renderBar(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('ContextBudgetBar manual compaction', () => {
  it('lets the user trigger context compaction from the usage popover', async () => {
    const onCompact = vi.fn().mockResolvedValue(undefined)
    renderBar(
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
    renderBar(
      <ContextBudgetBar
        used={14_200}
        max={272_000}
        input={14_200}
        cached={2_000}
        cacheWrite={1_200}
        turnInput={17_000}
        turnOutput={17}
        turnCached={2_500}
        turnCacheWrite={1_500}
        turnCalls={3}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Context 5% used/ }))

    // 14.2K prompt = 11K fresh + 2K cache read + 1.2K cache write.
    const current = await screen.findByRole('heading', { name: /Latest prompt/ })
    const currentSection = current.closest('section')
    expect(currentSection).not.toBeNull()
    expect(within(currentSection as HTMLElement).getByText('11K')).toBeInTheDocument()
    expect(within(currentSection as HTMLElement).getByText('2K')).toBeInTheDocument()
    expect(within(currentSection as HTMLElement).getByText('1.2K')).toBeInTheDocument()

    const turn = screen.getByRole('heading', { name: /This turn/ })
    const turnSection = turn.closest('section')
    expect(turnSection).not.toBeNull()
    expect(within(turnSection as HTMLElement).getByText('17')).toBeInTheDocument()
    expect(within(turnSection as HTMLElement).getByText('2.5K')).toBeInTheDocument()
    expect(within(turnSection as HTMLElement).getByText('1.5K')).toBeInTheDocument()
    expect(within(turnSection as HTMLElement).getByText('3 model calls')).toBeInTheDocument()
  })

  it('never shows cached tokens as a sibling of the full input total', async () => {
    // Regression: `turnInput` already contains the cache read and write, so
    // printing all three side by side invited the reader to add them up.
    renderBar(
      <ContextBudgetBar
        used={14_200}
        max={272_000}
        input={14_200}
        turnInput={17_000}
        turnOutput={17}
        turnCached={2_500}
        turnCacheWrite={1_500}
        turnCalls={3}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Context 5% used/ }))

    const turn = await screen.findByRole('heading', { name: /This turn/ })
    const turnSection = turn.closest('section') as HTMLElement
    // 17K - 2.5K - 1.5K = 13K charged at the plain input rate.
    expect(within(turnSection).getByText('13K')).toBeInTheDocument()
    expect(within(turnSection).queryByText('17K')).toBeNull()
  })

  it('shows what the turn cost', async () => {
    renderBar(
      <ContextBudgetBar
        used={14_200}
        max={272_000}
        input={14_200}
        turnInput={17_000}
        turnOutput={900}
        turnCalls={2}
        cost={{ estimated_usd: 0.0421, input_usd: 0.03, output_usd: 0.0121 }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Context 5% used/ }))

    const turn = await screen.findByRole('heading', { name: /This turn/ })
    const turnSection = turn.closest('section') as HTMLElement
    expect(within(turnSection).getByText('Cost')).toBeInTheDocument()
    expect(within(turnSection).getByText('$0.042')).toBeInTheDocument()
  })

  it('disables manual compaction while the session is working', async () => {
    const onCompact = vi.fn()
    renderBar(
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
