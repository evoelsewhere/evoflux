import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { GuidelinesModal } from '@/components/help/GuidelinesModal'
import { useUIStore } from '@/stores/useUIStore'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
}))

vi.mock('@/hooks/use-platform', () => ({
  usePlatform: () => ({ isTauri: false, os: 'unknown', isMacOverlay: false }),
}))

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: () => false,
}))

vi.mock('@/hooks/useModalFocus', () => ({
  useModalFocus: () => undefined,
}))

vi.mock('@/hooks/useReducedMotion', () => ({
  useReducedMotion: () => true,
}))

vi.mock('@/lib/motion', async () => {
  const actual = await vi.importActual<typeof import('@/lib/motion')>('@/lib/motion')
  return {
    ...actual,
    useMotionPreset: () => ({
      spring: { type: 'spring', stiffness: 400, damping: 40 },
      scale: 1,
      distance: 1,
    }),
  }
})

describe('GuidelinesModal', () => {
  beforeEach(() => {
    useUIStore.setState({
      guidelinesOpen: false,
      guidelinesTopicId: null,
    })
  })

  it('opens from the store and filters by keyword', () => {
    useUIStore.getState().openGuidelines()
    render(<GuidelinesModal />)

    expect(screen.getByTestId('guidelines-modal')).toBeInTheDocument()
    expect(screen.getByText('Getting started with EvoFlux')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('guidelines-search'), {
      target: { value: 'webbridge' },
    })
    expect(screen.getByTestId('guidelines-article-browser-webbridge')).toBeInTheDocument()
    expect(screen.queryByText('Getting started with EvoFlux')).not.toBeInTheDocument()
  })

  it('opens a topic deep-link from the store', () => {
    useUIStore.getState().openGuidelines('slash-goal')
    render(<GuidelinesModal />)

    expect(screen.getByRole('heading', { name: 'Durable Goal mode' })).toBeInTheDocument()
    expect(screen.getByText('Tricks')).toBeInTheDocument()
  })

  it('sidebar Help action opens guidelines via the store', () => {
    expect(useUIStore.getState().guidelinesOpen).toBe(false)
    useUIStore.getState().openGuidelines()
    expect(useUIStore.getState().guidelinesOpen).toBe(true)
    useUIStore.getState().closeGuidelines()
    expect(useUIStore.getState().guidelinesOpen).toBe(false)
  })
})
