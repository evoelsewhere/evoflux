import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InputBar, type ComposerSkill, type SlashCommand } from '@/components/InputBar'
import {
  findActiveSkillToken,
  findCommandDirectives,
  findSkillDirectives,
  splitQuotedContext,
} from '@/components/InputBar.skills'
import { BlockRenderer } from '@/components/BlockRenderer'

const slashCommands: SlashCommand[] = [
  { id: 'stop', label: 'Stop', description: 'Stop all agents' },
]

const skills: ComposerSkill[] = [
  { name: 'work-writing', description: 'Create Word documents' },
  { name: 'git-commit', description: 'Prepare a Git commit' },
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

describe('InputBar $skill picker', () => {
  it('does not offer skills from the / menu', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '/sk' } })
    expect(screen.queryByRole('listbox', { name: 'Slash commands' })).not.toBeInTheDocument()
    expect(screen.queryByText('Create Word documents')).not.toBeInTheDocument()
  })

  it('lists every skill on a bare $ and inserts $name', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '$' } })
    expect(screen.getByText('Create Word documents')).toBeInTheDocument()
    expect(screen.getByText('Prepare a Git commit')).toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(input).toHaveValue('$git-commit ')
    expect(screen.getByTestId('skill-chip')).toHaveTextContent('$git-commit')
  })

  it('filters by name and inserts only the token, mid-sentence too', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: 'Draft the report with $work' } })
    expect(screen.getByRole('listbox', { name: 'Skills' })).toBeInTheDocument()
    expect(screen.queryByText('Prepare a Git commit')).not.toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'Enter' })
    expect(input).toHaveValue('Draft the report with $work-writing ')
  })

  it('offers the picker on later lines and highlights several mentions', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: 'Use $work-writing first\nthen $git' } })
    expect(screen.getByRole('listbox', { name: 'Skills' })).toBeInTheDocument()
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(input).toHaveValue('Use $work-writing first\nthen $git-commit ')
    const chips = screen.getAllByTestId('skill-chip')
    expect(chips.map((chip) => chip.textContent)).toEqual(['$work-writing', '$git-commit'])
  })

  it('submits a $ mention with the user prompt', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<InputBar onSubmit={onSubmit} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '$work-writing Draft the report' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('$work-writing Draft the report', undefined, 'steer')
    })
  })

  it('keeps $ inert where the backend would ignore it', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    // Quoted context lines are not read.
    fireEvent.change(input, { target: { value: '> quoted $work' } })
    expect(screen.queryByRole('listbox', { name: 'Skills' })).not.toBeInTheDocument()

    // Nor are fenced code blocks.
    fireEvent.change(input, { target: { value: '```\necho $work' } })
    expect(screen.queryByRole('listbox', { name: 'Skills' })).not.toBeInTheDocument()

    // An unknown name never chips.
    fireEvent.change(input, { target: { value: '$not-a-skill do it' } })
    expect(screen.queryByTestId('skill-chip')).not.toBeInTheDocument()
  })

  it('reads the WebBridge catalog shape from category skill slash entries', () => {
    render(
      <InputBar
        onSubmit={vi.fn()}
        slashCommands={[
          ...slashCommands,
          {
            id: 'skill:pdf',
            label: 'pdf',
            description: 'Extracts PDF text',
            category: 'skill',
            insertText: '$pdf ',
            keepInputOpen: true,
          },
        ]}
      />,
    )
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '$p' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(input).toHaveValue('$pdf ')
  })

  it('leaves the @ picker working beside the $ picker', () => {
    render(
      <InputBar
        onSubmit={vi.fn()}
        slashCommands={slashCommands}
        skills={skills}
        fileRefs={[{ path: 'src/auth.py', name: 'auth.py', type: 'file' }]}
      />,
    )
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '@auth' } })
    expect(
      screen.getByRole('listbox', { name: 'Reference workspace file' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('listbox', { name: 'Skills' })).not.toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'Enter' })
    expect(input).toHaveValue('@src/auth.py ')
    expect(screen.getByTestId('mention-chip')).toHaveTextContent('@src/auth.py')
  })

  it('highlights a known slash command while it is being typed', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '/sto' } })
    expect(screen.queryByTestId('command-chip')).not.toBeInTheDocument()

    fireEvent.change(input, { target: { value: '/stop now' } })
    expect(screen.getByTestId('command-chip')).toHaveTextContent('/stop')
  })

  it('teaches the trigger characters through the placeholder', () => {
    const { rerender } = render(
      <InputBar
        onSubmit={vi.fn()}
        slashCommands={slashCommands}
        skills={skills}
        onFileRefsNeeded={vi.fn()}
      />,
    )
    expect(screen.getByRole('textbox', { name: 'Message input' })).toHaveAttribute(
      'placeholder',
      'Ask anything — @ tag files/folders, $ use skills, / for commands',
    )

    // A composer without pickers must not advertise them.
    rerender(<InputBar onSubmit={vi.fn()} placeholder="Ask a question…" />)
    expect(screen.getByRole('textbox', { name: 'Message input' })).toHaveAttribute(
      'placeholder',
      'Ask a question…',
    )
  })
})

describe('$skill-name grammar (mirrors app/agent/skills/invocation.py)', () => {
  it('finds every mention anywhere in the message', () => {
    expect(findSkillDirectives('$work-writing draft it')).toEqual([
      { start: 0, end: 13, name: 'work-writing' },
    ])
    expect(findSkillDirectives('first\nuse $pdf-tools, then ($git-commit).')).toEqual([
      { start: 10, end: 20, name: 'pdf-tools' },
      { start: 28, end: 39, name: 'git-commit' },
    ])
  })

  it('applies the backend boundary rules', () => {
    // Glued to a word character or another $.
    expect(findSkillDirectives('email me@host.com$work-writing')).toEqual([])
    expect(findSkillDirectives('$$work-writing')).toEqual([])
    // Not followed by whitespace, punctuation or the end.
    expect(findSkillDirectives('$work-writing/sub')).toEqual([])
    expect(findSkillDirectives('$Work-Writing')).toEqual([])
    // Trailing punctuation stays outside the name.
    expect(findSkillDirectives('try "$pdf-tools"')).toEqual([
      { start: 5, end: 15, name: 'pdf-tools' },
    ])
  })

  it('ignores quoted context lines and fenced code blocks', () => {
    const text = '> quoted $pdf-tools\n```\n$git-commit\n```\n  > also quoted $docx\nreal $pdf-tools'
    const names = findSkillDirectives(text).map((range) => range.name)
    expect(names).toEqual(['pdf-tools'])
    expect(findSkillDirectives(text)[0]?.start).toBe(text.lastIndexOf('$pdf-tools'))
  })

  it('uses the roster when given and a heuristic otherwise', () => {
    // Prices, shell variables and argument placeholders are not mentions.
    expect(findSkillDirectives('it costs $5 and $ARGUMENTS stay plain')).toEqual([])
    expect(findSkillDirectives('$pdf and $docx', new Set(['docx']))).toEqual([
      { start: 9, end: 14, name: 'docx' },
    ])
    expect(findSkillDirectives('$5', new Set(['5']))).toEqual([{ start: 0, end: 2, name: '5' }])
  })

  it('locates the $ token under the caret on any readable line', () => {
    expect(findActiveSkillToken('hello\nuse $pd', 13)).toEqual({ start: 10, end: 13, query: 'pd' })
    expect(findActiveSkillToken('> quote $pd', 11)).toBeNull()
    expect(findActiveSkillToken('```\n$pd', 7)).toBeNull()
    expect(findActiveSkillToken('cost5$pd', 8)).toBeNull()
  })

  it('splits the composer quote block off without losing a byte', () => {
    const message = '> selected line\n> second line\n\n/goal ship it'
    const { quote, body } = splitQuotedContext(message)

    expect(quote).toBe('> selected line\n> second line\n\n')
    expect(body).toBe('/goal ship it')
    expect(quote + body).toBe(message)

    expect(splitQuotedContext('/goal ship it')).toEqual({ quote: '', body: '/goal ship it' })
    // Nothing but quotes: no body to run a command from.
    expect(splitQuotedContext('> only a quote')).toEqual({ quote: '', body: '> only a quote' })
  })

  it('treats only a leading, known command as a command', () => {
    expect(findCommandDirectives('/goal Ship it')).toEqual([{ start: 0, end: 5, name: 'goal' }])
    expect(findCommandDirectives('please run /goal Ship it')).toEqual([])
    expect(findCommandDirectives('/goal Ship it', new Set(['compact']))).toEqual([])
  })
})

describe('sent messages', () => {
  it('renders every sent $ mention as a chip', () => {
    render(
      <BlockRenderer
        block={{
          id: 'user-dollar',
          type: 'user',
          content: '$work-writing Draft the report, then $git-commit it',
        }}
        isStreaming={false}
      />,
    )

    const chips = screen.getAllByTestId('skill-chip')
    expect(chips.map((chip) => chip.textContent)).toEqual(['$work-writing', '$git-commit'])
    expect(chips[0]).toHaveClass('font-semibold')
  })

  it('highlights built-in and custom slash commands after send', () => {
    const { rerender } = render(
      <BlockRenderer
        block={{ id: 'user-goal', type: 'user', content: '/goal Ship the release' }}
        isStreaming={false}
      />,
    )
    expect(screen.getByTestId('command-chip')).toHaveTextContent('/goal')

    rerender(
      <BlockRenderer
        block={{ id: 'user-custom', type: 'user', content: '/git:commit --staged' }}
        isStreaming={false}
      />,
    )
    expect(screen.getByTestId('command-chip')).toHaveTextContent('/git:commit')
  })

  it('highlights executable, flags, and paths in sent shell commands', () => {
    render(
      <BlockRenderer
        block={{ id: 'user-shell', type: 'user', content: '! python -m pytest tests/test_api.py', extra: { kind: 'user_shell' } }}
        isStreaming={false}
      />,
    )

    expect(screen.getByText('Shell')).toBeInTheDocument()
    expect(screen.getByText('python')).toHaveClass('text-(--color-accent)')
    expect(screen.getByText('-m')).toHaveClass('text-(--color-warning)')
    expect(screen.getByText('tests/test_api.py')).toHaveClass('text-(--color-success)')
  })
})
