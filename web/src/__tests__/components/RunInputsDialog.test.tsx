import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { RunInputsDialog } from '@/components/RunInputsDialog'

async function choose(label: string, option: string) {
  fireEvent.click(screen.getByRole('combobox', { name: label }))
  const item = await screen.findByRole('option', { name: option })
  fireEvent.mouseMove(item)
  fireEvent.pointerDown(item, { pointerType: 'mouse' })
  fireEvent.mouseUp(item)
  fireEvent.click(item)
}

describe('RunInputsDialog', () => {
  it('preserves enum strings and boolean conversion through shared selects', async () => {
    const onRun = vi.fn().mockResolvedValue(undefined)
    render(
      <RunInputsDialog
        request={{
          name: 'release',
          prefilled: {},
          inputs: [
            {
              name: 'strategy',
              description: 'Release strategy',
              type: 'enum',
              required: true,
              options: ['fast', 'safe'],
            },
            {
              name: 'dry_run',
              description: 'Do not publish changes',
              type: 'boolean',
              required: false,
              default: false,
            },
          ],
        }}
        onCancel={vi.fn()}
        onRun={onRun}
      />,
    )

    await choose('strategy', 'safe')
    await choose('dry_run', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))

    await waitFor(() => {
      expect(onRun).toHaveBeenCalledWith({ strategy: 'safe', dry_run: true })
    })
  })
})
