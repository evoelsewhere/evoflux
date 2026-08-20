import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TranscriptHistoryControl } from '@/components/TranscriptHistoryControl'
import { useTeamStore } from '@/stores/useTeamStore'

describe('TranscriptHistoryControl', () => {
  beforeEach(() => {
    useTeamStore.setState({
      hasMore: false,
      historyLoadError: null,
      _loadingOlder: false,
    })
  })

  it('keeps server history reachable when the loaded page has no hidden turns', () => {
    const onLoadOlder = vi.fn()
    useTeamStore.setState({ hasMore: true })

    render(
      <TranscriptHistoryControl
        hiddenTurnCount={0}
        revealStep={48}
        onLoadOlder={onLoadOlder}
        onRevealLoaded={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Load earlier messages' }))
    expect(onLoadOlder).toHaveBeenCalledOnce()
  })

  it('reveals client-hidden turns before requesting another server page', () => {
    const onLoadOlder = vi.fn()
    const onRevealLoaded = vi.fn()
    useTeamStore.setState({ hasMore: true })

    render(
      <TranscriptHistoryControl
        hiddenTurnCount={12}
        revealStep={8}
        onLoadOlder={onLoadOlder}
        onRevealLoaded={onRevealLoaded}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Show 8 earlier turns' }))
    expect(onRevealLoaded).toHaveBeenCalledOnce()
    expect(onLoadOlder).not.toHaveBeenCalled()
  })

  it('offers a retry after a server-page failure', () => {
    const onLoadOlder = vi.fn()
    useTeamStore.setState({
      hasMore: true,
      historyLoadError: 'network unavailable',
    })

    render(
      <TranscriptHistoryControl
        hiddenTurnCount={0}
        revealStep={48}
        onLoadOlder={onLoadOlder}
        onRevealLoaded={vi.fn()}
      />,
    )

    const button = screen.getByRole('button', { name: 'Retry earlier messages' })
    expect(button).toHaveAttribute('title', 'network unavailable')
    fireEvent.click(button)
    expect(onLoadOlder).toHaveBeenCalledOnce()
  })
})
