import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

describe('DialogContent', () => {
  it('dims the page behind it without blurring it', () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Graph explorer</DialogTitle>
        </DialogContent>
      </Dialog>,
    )

    const overlay = document.querySelector('[data-slot="dialog-overlay"]')
    expect(overlay).toBeInTheDocument()
    expect(overlay?.className).not.toMatch(/backdrop-blur/)
  })
})
