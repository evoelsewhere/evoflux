import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const storeMock = vi.hoisted(() => ({
  sendMessage: vi.fn(async (_prompt: string) => true),
}))

vi.mock('@/stores/useTeamStore', () => ({
  useTeamStore: (
    selector: (s: { sendMessage: (prompt: string) => Promise<boolean> }) => unknown,
  ) => selector({ sendMessage: storeMock.sendMessage }),
}))

import { UiBlockRenderer } from '@/components/ui/UiBlockRenderer'
import { evaluateFormula } from '@/components/ui/safe-formula'
import type { UiBlockNode } from '@/components/ui/ui-block-types'

describe('UiFlashcards (interactive catalog)', () => {
  const flashcards: UiBlockNode = {
    type: 'flashcards',
    title: 'Quiz',
    cards: [
      { front: 'What does CPU throttling mean?', back: 'Reducing clock speed to stay cool.' },
      { front: 'What is RAM?', back: 'Fast, volatile working memory.' },
      { front: 'What is an SSD?', back: 'Solid-state storage with no moving parts.' },
    ],
  }

  it('flips the card on click, revealing the back', () => {
    render(<UiBlockRenderer blocks={[flashcards]} />)
    const flip = screen.getByRole('button', { name: 'Flip card' })
    expect(screen.getByText('What does CPU throttling mean?')).toBeVisible()
    expect(flip).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(flip)
    expect(flip).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('Reducing clock speed to stay cool.')).toBeVisible()
    fireEvent.click(flip)
    expect(flip).toHaveAttribute('aria-pressed', 'false')
  })

  it('shows "Card n of m" with prev/next navigation when multiple cards', () => {
    render(<UiBlockRenderer blocks={[flashcards]} />)
    expect(screen.getByText('Card 1 of 3')).toBeInTheDocument()
    const prev = screen.getByRole('button', { name: 'Previous card' })
    const next = screen.getByRole('button', { name: 'Next card' })
    expect(prev).toBeDisabled()
    fireEvent.click(next)
    expect(screen.getByText('Card 2 of 3')).toBeInTheDocument()
    expect(screen.getByText('What is RAM?')).toBeVisible()
    fireEvent.click(next)
    expect(screen.getByText('Card 3 of 3')).toBeInTheDocument()
    expect(next).toBeDisabled()
  })

  it('omits navigation for a single card', () => {
    render(<UiBlockRenderer blocks={[{ type: 'flashcards', cards: [{ front: 'q', back: 'a' }] }]} />)
    expect(screen.getByText('Card 1 of 1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Next card' })).not.toBeInTheDocument()
  })
})

describe('UiChecklist (interactive catalog)', () => {
  const checklist: UiBlockNode = {
    type: 'checklist',
    title: 'Roast ingredients',
    description: 'Everything you need before you start.',
    items: [
      { label: 'Lamb', detail: 'shoulder, 3.6 kg', checked: true },
      { label: 'Potatoes', detail: '2.5 kg' },
      { label: 'Rosemary' },
    ],
  }

  it('starts from the checked flags and updates the counter and progress bar', () => {
    render(<UiBlockRenderer blocks={[checklist]} />)
    expect(screen.getByText('Roast ingredients')).toBeInTheDocument()
    expect(screen.getByText('1 of 3 done')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Checklist progress' })
    expect(bar).toHaveAttribute('aria-valuenow', '1')

    const lamb = screen.getByRole('checkbox', { name: 'Lamb' })
    expect(lamb).toBeChecked()
    fireEvent.click(lamb)
    expect(screen.getByText('0 of 3 done')).toBeInTheDocument()
    expect(bar).toHaveAttribute('aria-valuenow', '0')

    fireEvent.click(lamb)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Potatoes' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Rosemary' }))
    expect(screen.getByText('3 of 3 done')).toBeInTheDocument()
    expect(bar).toHaveAttribute('aria-valuenow', '3')
  })

  it('strikes and dims checked items', () => {
    render(<UiBlockRenderer blocks={[checklist]} />)
    const checked = screen.getByRole('checkbox', { name: 'Lamb' })
    const label = checked.parentElement?.querySelector('span span')
    expect(label?.className).toContain('line-through')
    expect(label?.className).toContain('text-(--color-text-muted)')
  })
})

describe('UiCalculator (interactive catalog)', () => {
  const billSplit: UiBlockNode = {
    type: 'calculator',
    description: 'Split the bill evenly.',
    inputs: [
      { name: 'total', label: 'Total', value: 90, unit: '$' },
      { name: 'people', label: 'People', value: 3, min: 1, step: 1 },
    ],
    outputs: [{ label: 'Each pays', formula: 'total / people', unit: '$', decimals: 2 }],
  }

  it('computes outputs from the initial values', () => {
    render(<UiBlockRenderer blocks={[billSplit]} />)
    expect(screen.getByText('Each pays')).toBeInTheDocument()
    expect(screen.getByText('30.00')).toBeInTheDocument()
    expect(screen.getByText('$', { selector: 'dd span' })).toBeInTheDocument()
  })

  it('recomputes live on every keystroke', () => {
    render(<UiBlockRenderer blocks={[billSplit]} />)
    const total = screen.getByLabelText('Total ($)')
    fireEvent.change(total, { target: { value: '120' } })
    expect(screen.getByText('40.00')).toBeInTheDocument()
    fireEvent.change(total, { target: { value: '120.5' } })
    expect(screen.getByText('40.17')).toBeInTheDocument()
  })

  it('steppers move by step and respect min', () => {
    render(<UiBlockRenderer blocks={[billSplit]} />)
    const increase = screen.getByRole('button', { name: 'Increase People' })
    const decrease = screen.getByRole('button', { name: 'Decrease People' })
    fireEvent.click(increase)
    expect(screen.getByLabelText('People')).toHaveValue(4)
    expect(screen.getByText('22.50')).toBeInTheDocument()
    fireEvent.click(decrease)
    fireEvent.click(decrease)
    fireEvent.click(decrease)
    // Clamped at min=1.
    expect(screen.getByLabelText('People')).toHaveValue(1)
    expect(screen.getByText('90.00')).toBeInTheDocument()
  })

  it('roast planner outputs recompute from guests', () => {
    const roast: UiBlockNode = {
      type: 'calculator',
      inputs: [{ name: 'guests', label: 'Guests', value: 8, min: 1, step: 1 }],
      outputs: [
        { label: 'Lamb', formula: 'guests * 0.45', unit: 'kg', decimals: 2 },
        { label: 'Potatoes', formula: 'guests*0.5', unit: 'kg', decimals: 1 },
      ],
    }
    render(<UiBlockRenderer blocks={[roast]} />)
    expect(screen.getByText('3.60')).toBeInTheDocument()
    expect(screen.getByText('4.0')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Increase Guests' }))
    expect(screen.getByText('4.05')).toBeInTheDocument()
    expect(screen.getByText('4.5')).toBeInTheDocument()
  })

  it('surfaces an invalid formula as an inline error on the output row', () => {
    const broken: UiBlockNode = {
      type: 'calculator',
      inputs: [{ name: 'total', label: 'Total', value: 10 }],
      outputs: [
        { label: 'Fine', formula: 'total * 2' },
        { label: 'Broken', formula: 'alert(1)' },
      ],
    }
    render(<UiBlockRenderer blocks={[broken]} />)
    expect(screen.getByText('20.00')).toBeInTheDocument()
    const error = screen.getByRole('alert')
    // `alert(1)` parses as identifier `alert` + parens — rejected as an
    // unknown input; genuinely malformed tokens get an unsupported-char error.
    expect(error.textContent).toMatch(/Unknown input "alert"/)
  })
})

describe('safe-formula parser', () => {
  const values = { total: 90, people: 3, guests: 8 }

  it('evaluates arithmetic with precedence and parentheses', () => {
    expect(evaluateFormula('total / people', values)).toEqual({ ok: true, value: 30 })
    expect(evaluateFormula('(total + 10) / 2', values)).toEqual({ ok: true, value: 50 })
    expect(evaluateFormula('guests * 0.45', values)).toEqual({ ok: true, value: 3.6 })
    expect(evaluateFormula('2 + 3 * 4', {})).toEqual({ ok: true, value: 14 })
    expect(evaluateFormula('-total + 2', values)).toEqual({ ok: true, value: -88 })
  })

  it('rejects anything outside numbers, names, + - * / ( )', () => {
    for (const formula of [
      'alert(1)',
      'eval(1)',
      'total ** 2',
      '__import__(total)',
      'total; people',
      'total, people',
      '`total`',
      'total # comment',
      'window.location',
      '(total + 1',
      'total /',
      '',
    ]) {
      const result = evaluateFormula(formula, values)
      expect(result.ok, formula).toBe(false)
      expect(result.error, formula).toBeTruthy()
    }
  })

  it('rejects unknown input references', () => {
    const result = evaluateFormula('tax * 2', values)
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/Unknown input "tax"/)
  })

  it('rejects non-finite results', () => {
    const result = evaluateFormula('total / 0', values)
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/finite/)
  })
})
