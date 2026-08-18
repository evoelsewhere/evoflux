import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { GitAiResultDialog } from '@/components/GitAiResultDialog'

it('renders structured PR text and finding count', () => {
  render(
    <GitAiResultDialog
      result={{
        kind: 'pr',
        summary: 'PR draft generated',
        title: 'Improve semantic editor',
        body: 'Adds guarded changes and verification.',
        message: null,
        findings: ['one', 'two'],
        change_set: null,
        evidence_sha256: 'a'.repeat(64),
      }}
      onClose={vi.fn()}
    />,
  )

  expect(screen.getByText('Improve semantic editor')).toBeInTheDocument()
  expect(screen.getByText('Adds guarded changes and verification.')).toBeInTheDocument()
  expect(screen.getByText('2 findings added to Problems.')).toBeInTheDocument()
})
