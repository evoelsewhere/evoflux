import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

describe('DialogContent', () => {
  it('can disable backdrop blur for GPU-heavy desktop content', () => {
    render(
      <Dialog open>
        <DialogContent overlayBlur={false}>
          <DialogTitle>Graph explorer</DialogTitle>
        </DialogContent>
      </Dialog>,
    )

    const overlay = document.querySelector('[data-slot="dialog-overlay"]')
    expect(overlay).toBeInTheDocument()
    expect(overlay).not.toHaveClass('supports-backdrop-filter:backdrop-blur-xs')
  })
})
