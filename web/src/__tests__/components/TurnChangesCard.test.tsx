import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TurnChangesCard } from '@/components/TurnChangesCard'
import type { TurnChangesPending } from '@/api/types'

const changes: TurnChangesPending = {
  sessionId: 'session-1',
  additions: 503,
  deletions: 23,
  files: [
    { path: 'desktop/src-tauri/src/main.rs', status: 'modified', additions: 1, deletions: 1 },
    { path: 'web/public/appearance-init.js', status: 'modified', additions: 2, deletions: 2 },
    { path: 'web/src/components/SettingsScreen.tsx', status: 'modified', additions: 4, deletions: 1 },
    { path: 'web/src/components/TurnChangesCard.tsx', status: 'added', additions: 180, deletions: 0 },
  ],
}

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

describe('TurnChangesCard', () => {
  it('shows totals and expands the remaining file list', () => {
    render(<TurnChangesCard changes={changes} />)

    expect(screen.getByText('Edited 4 files')).toBeInTheDocument()
    expect(screen.getByText('+503')).toBeInTheDocument()
    expect(screen.getByText('−23')).toBeInTheDocument()
    expect(screen.getByText('desktop/src-tauri/src/main.rs')).toBeInTheDocument()
    expect(screen.queryByText('web/src/components/TurnChangesCard.tsx')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Show 1 more files' }))

    expect(screen.getByText('web/src/components/TurnChangesCard.tsx')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show fewer files' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })
})
