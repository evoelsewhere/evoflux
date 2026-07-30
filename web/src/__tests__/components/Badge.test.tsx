import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Badge } from '@/components/ui/badge'

describe('Badge', () => {
  it('renders accessible content with the requested variant', () => {
    render(<Badge variant="destructive">Failed</Badge>)

    const badge = screen.getByText('Failed')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute('data-slot', 'badge')
    expect(badge.className).toContain('text-(--color-error)')
  })
})
