import { createPortal } from 'react-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useTauriDrag } from '@/hooks/use-tauri-drag'

const windowApi = vi.hoisted(() => ({
  startDragging: vi.fn(),
  toggleMaximize: vi.fn(),
}))

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => windowApi,
}))

vi.mock('@/hooks/use-platform', () => ({
  getPlatform: () => ({ isTauri: true }),
}))

function DragHeaderWithPortals() {
  const dragHandlers = useTauriDrag()
  return (
    <header {...dragHandlers}>
      <div data-testid="bare-header">Drag region</div>
      {createPortal(<button type="button">Portal action</button>, document.body)}
      {createPortal(
        <div data-no-drag data-testid="portal-popup-background">
          Popup background
        </div>,
        document.body,
      )}
    </header>
  )
}

describe('useTauriDrag portal safety', () => {
  beforeEach(() => {
    windowApi.startDragging.mockReset()
    windowApi.toggleMaximize.mockReset()
  })

  it('does not start a window drag from interactive portal content', () => {
    render(<DragHeaderWithPortals />)

    fireEvent.mouseDown(screen.getByRole('button', { name: 'Portal action' }), {
      buttons: 1,
      detail: 1,
    })

    expect(windowApi.startDragging).not.toHaveBeenCalled()
  })

  it('keeps popup backgrounds inert while bare header space still drags', () => {
    render(<DragHeaderWithPortals />)

    fireEvent.mouseDown(screen.getByTestId('portal-popup-background'), {
      buttons: 1,
      detail: 1,
    })
    expect(windowApi.startDragging).not.toHaveBeenCalled()

    fireEvent.mouseDown(screen.getByTestId('bare-header'), {
      buttons: 1,
      detail: 1,
    })
    expect(windowApi.startDragging).toHaveBeenCalledOnce()
  })
})
