import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InputBar, type SlashCommand } from '@/components/InputBar'
import { findSkillDirectives } from '@/components/InputBar.skills'
import { BlockRenderer } from '@/components/BlockRenderer'

const slashCommands: SlashCommand[] = [
  { id: 'stop', label: 'Stop', description: 'Stop all agents' },
  {
    id: 'skill',
    label: 'skill:',
    displayName: 'skill:',
    insertText: 'skill:',
    description: 'Choose a skill to use for this message',
    category: 'skill',
    keepInputOpen: true,
    appendSpace: false,
    hideAfterPrefix: 'skill:',
  },
  {
    id: 'skill:docx',
    label: 'docx',
    displayName: 'skill:docx',
    insertText: 'skill:docx',
    description: 'Create Word documents',
    category: 'skill',
    keepInputOpen: true,
    filterPrefix: 'skill:',
  },
  {
    id: 'skill:git:commit',
    label: 'git:commit',
    displayName: 'skill:git:commit',
    insertText: 'skill:git:commit',
    description: 'Prepare a Git commit',
    category: 'skill',
    keepInputOpen: true,
    filterPrefix: 'skill:',
  },
]

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  })
})

describe('InputBar skill directives', () => {
  it('suggests /skill: from /sk, then opens and commits a skill choice', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '/sk' } })
    expect(screen.getByText('Choose a skill to use for this message')).toBeInTheDocument()
    expect(screen.queryByText('Create Word documents')).not.toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'Enter' })

    expect(input).toHaveValue('/skill:')
    expect(screen.getByText('Create Word documents')).toBeInTheDocument()
    expect(screen.getByText('Prepare a Git commit')).toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'Enter' })

    expect(input).toHaveValue('/skill:docx ')
    expect(screen.getByTestId('skill-chip')).toHaveTextContent('/skill:docx')
  })

  it('submits the directive with the user prompt', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<InputBar onSubmit={onSubmit} slashCommands={slashCommands} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '/skill:docx Draft the report' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        '/skill:docx Draft the report',
        undefined,
      )
    })
  })

  it('recognizes nested skill directives after quoted context', () => {
    const text = '> selected context\n\n/skill:git:commit Commit this change'

    expect(findSkillDirectives(text)).toEqual([
      { start: 20, end: 37, name: 'git:commit' },
    ])
    expect(findSkillDirectives(text, new Set(['docx']))).toEqual([])
  })

  it('keeps the selected skill highlighted after the message is sent', () => {
    render(
      <BlockRenderer
        block={{
          id: 'user-skill',
          type: 'user',
          content: '/skill:docx Draft the report',
        }}
        isStreaming={false}
      />,
    )

    const chip = screen.getByTestId('skill-chip')
    expect(chip).toHaveTextContent('/skill:docx')
    expect(chip).toHaveClass('font-semibold')
  })
})
