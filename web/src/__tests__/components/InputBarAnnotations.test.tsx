import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BlockRenderer } from '@/components/BlockRenderer'
import { InputBar } from '@/components/InputBar'
import {
  composeAnnotatedMessage,
  describeAnnotation,
  parseAnnotatedMessage,
  type DocumentAnnotation,
} from '@/lib/document-annotations'
import { useDocumentAnnotationsStore } from '@/stores/useDocumentAnnotationsStore'

const chart: DocumentAnnotation = {
  id: 'a1',
  file: 'deck.pptx',
  slide: 7,
  shapes: [{ id: 12, name: 'Chart 3' }],
  area: { x: 10.04, y: 20, w: 50, h: 40 },
  text: 'Quarterly P&L',
  instruction: 'Keep the colors in a unified tone.',
  label: 'Slide 7 · Chart 3',
}

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
  })
  vi.stubGlobal('ResizeObserver', class {
    observe = vi.fn()
    disconnect = vi.fn()
  })
  useDocumentAnnotationsStore.setState({ pending: {}, submitRequest: null })
})

describe('document annotation messages', () => {
  it('round-trips the annotation block and activates the Skill', () => {
    const message = composeAnnotatedMessage('Also check the legend.', [chart])

    expect(message.startsWith('Also check the legend.\n\n$office-annotation-edit\n<evoflux-annotations>\n')).toBe(true)
    expect(parseAnnotatedMessage(message)).toEqual({
      text: 'Also check the legend.',
      annotations: [{
        n: 1,
        file: 'deck.pptx',
        slide: 7,
        shapes: [{ id: 12, name: 'Chart 3' }],
        text: 'Quarterly P&L',
        instruction: 'Keep the colors in a unified tone.',
      }],
    })
    expect(parseAnnotatedMessage('plain text')).toBeNull()
    // The server stores what multipart delivered: CRLF line breaks.
    expect(parseAnnotatedMessage(message.replace(/\n/g, '\r\n'))?.annotations).toHaveLength(1)
  })

  it('carries a workbook annotation\'s sheet and range', () => {
    const cells: DocumentAnnotation = {
      ...chart,
      file: 'model.xlsx',
      slide: 2,
      sheet: 'Model',
      range: 'B3:D8',
      shapes: [],
      label: 'Model · B3:D8',
    }

    const parsed = parseAnnotatedMessage(composeAnnotatedMessage('', [cells]))

    expect(parsed?.annotations[0]).toMatchObject({ file: 'model.xlsx', slide: 2, sheet: 'Model', range: 'B3:D8' })
    expect(describeAnnotation(parsed!.annotations[0])).toBe('Model · B3:D8')
  })

  it('folds pending annotations into the next message and clears them', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    useDocumentAnnotationsStore.getState().add('s1', chart)
    render(<InputBar onSubmit={onSubmit} sessionId="s1" />)

    expect(screen.getByText('Annotations: 1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    const [sent] = onSubmit.mock.calls[0] as [string]
    expect(parseAnnotatedMessage(sent)?.annotations[0].slide).toBe(7)
    expect(useDocumentAnnotationsStore.getState().pending.s1).toBeUndefined()
  })

  it('submits when the viewer asks, and restores the batch if the send is rejected', async () => {
    const onSubmit = vi.fn().mockResolvedValue(false)
    render(<InputBar onSubmit={onSubmit} sessionId="s1" />)

    act(() => {
      useDocumentAnnotationsStore.getState().add('s1', chart)
      useDocumentAnnotationsStore.getState().requestSubmit('s1')
    })

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(useDocumentAnnotationsStore.getState().pending.s1).toHaveLength(1))
  })

  it('shows a sent annotation message as a chip instead of the raw block', () => {
    render(
      <BlockRenderer
        block={{ type: 'user', content: composeAnnotatedMessage('', [chart]), timestamp: new Date() } as never}
        isStreaming={false}
      />,
    )

    const chip = screen.getByTestId('annotations-chip')
    expect(chip).toHaveTextContent('Annotations: 1')
    expect(screen.queryByText(/evoflux-annotations/)).not.toBeInTheDocument()
    fireEvent.click(chip)
    expect(screen.getByText('Keep the colors in a unified tone.')).toBeInTheDocument()
  })
})
