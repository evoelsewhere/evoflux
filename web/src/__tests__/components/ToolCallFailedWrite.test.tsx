import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ToolCall } from '@/components/ToolCall'

const ARGS = JSON.stringify({ path: 'C:/repos/api/SOURCE.txt', content: 'source\n' })

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

describe('file mutation results', () => {
  it('does not present a refused write as written', () => {
    render(
      <ToolCall
        name="write"
        args={ARGS}
        done
        result={"Error: Path 'C:\\repos\\api\\SOURCE.txt' is read-only in this session"}
      />,
    )

    expect(screen.getByText('Write failed')).toBeInTheDocument()
    expect(screen.queryByText('Wrote')).not.toBeInTheDocument()
    // No "+2": nothing was added.
    expect(screen.queryByText('+2')).not.toBeInTheDocument()
  })

  it('reports a successful write with its line count', () => {
    render(<ToolCall name="write" args={ARGS} done result="Written 7 bytes to SOURCE.txt" />)

    expect(screen.getByText('Wrote')).toBeInTheDocument()
    expect(screen.getByText('+2')).toBeInTheDocument()
  })
})
