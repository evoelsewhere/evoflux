import { fireEvent, render, screen } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { UserMessageNavigationRail } from '@/components/UserMessageNavigationRail'
import type { UserMessageNavigationItem } from '@/utils/user-message-navigation'

const ITEMS: UserMessageNavigationItem[] = Array.from({ length: 4 }, (_, index) => ({
  id: `message-${index + 1}`,
  label: `Prompt ${index + 1}`,
  response: `Response ${index + 1}`,
  toolNames: index === 0 ? ['shell'] : [],
  turnIndex: index * 2,
}))

function Harness({
  items = ITEMS,
  onNavigate,
}: {
  items?: UserMessageNavigationItem[]
  onNavigate: (messageId: string, behavior: ScrollBehavior) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  return (
    <div>
      <div ref={containerRef}>
        {items.map((item) => (
          <div key={item.id} data-user-message-navigation-anchor={item.id} />
        ))}
      </div>
      <UserMessageNavigationRail
        items={items}
        containerRef={containerRef}
        onNavigate={onNavigate}
      />
    </div>
  )
}

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('UserMessageNavigationRail', () => {
  it('shows a prompt preview and navigates on click', () => {
    const onNavigate = vi.fn()
    render(<Harness onNavigate={onNavigate} />)

    expect(screen.getByRole('navigation', { name: 'User messages' })).toHaveClass(
      '@[48rem]/agent-view:flex',
    )
    const firstMarker = screen.getByRole('button', { name: 'Jump to user message 1' })

    fireEvent.mouseEnter(firstMarker)
    expect(screen.getByRole('tooltip')).toHaveTextContent('Prompt 1')
    expect(screen.getByRole('tooltip')).toHaveTextContent('Response 1')
    expect(screen.getByRole('tooltip')).toHaveTextContent('shell')

    fireEvent.click(firstMarker)
    expect(onNavigate).toHaveBeenCalledWith('message-1', 'smooth')
  })

  it('stays hidden for a single user message', () => {
    render(<Harness items={ITEMS.slice(0, 1)} onNavigate={vi.fn()} />)
    expect(screen.queryByRole('navigation', { name: 'User messages' })).not.toBeInTheDocument()
  })
})
