import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InputBar, type ComposerSkill, type SlashCommand } from '@/components/InputBar'
import {
  findCommandDirectives,
  findSkillDirectives,
  splitQuotedContext,
} from '@/components/InputBar.skills'
import { BlockRenderer } from '@/components/BlockRenderer'

const slashCommands: SlashCommand[] = [
  { id: 'stop', label: 'Stop', description: 'Stop all agents' },
]

const skills: ComposerSkill[] = [
  {
    name: 'work-writing',
    label: 'work-writing',
    description: 'Create Word documents',
    prompt: 'Use $work-writing to draft this document.',
  },
  { name: 'git:commit', label: 'git:commit', description: 'Prepare a Git commit' },
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
  it('no longer offers skills from the / menu', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '/sk' } })
    expect(screen.queryByRole('listbox', { name: 'Slash commands' })).not.toBeInTheDocument()
    expect(screen.queryByText('Create Word documents')).not.toBeInTheDocument()
  })

  it('lists every skill on a bare $ and commits the chosen one', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '$' } })
    expect(screen.getByText('Create Word documents')).toBeInTheDocument()
    expect(screen.getByText('Prepare a Git commit')).toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(input).toHaveValue('$git:commit ')
    expect(screen.getByTestId('skill-chip')).toHaveTextContent('$git:commit')
  })

  it('submits a $ directive with the user prompt', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<InputBar onSubmit={onSubmit} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '$work-writing Draft the report' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        '$work-writing Draft the report',
        undefined,
        'steer',
      )
    })
  })

  it('opens the $ picker and commits the shorthand directive', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: '$work' } })
    expect(screen.getByRole('listbox', { name: 'Skills' })).toBeInTheDocument()
    expect(screen.getByText('Create Word documents')).toBeInTheDocument()
    expect(screen.queryByText('Prepare a Git commit')).not.toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'Enter' })

    expect(input).toHaveValue('Use $work-writing to draft this document. ')
    expect(screen.getByTestId('skill-chip')).toHaveTextContent('$work-writing')
  })

  it('seeds the starter prompt only when it opens the message', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    // A prompt written around its own directive is inserted whole.
    fireEvent.change(input, { target: { value: '$work' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(input).toHaveValue('Use $work-writing to draft this document. ')

    // Mid-sentence, only the directive lands.
    fireEvent.change(input, { target: { value: 'Draft the report with $work' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(input).toHaveValue('Draft the report with $work-writing ')
  })

  it('keeps $ inert where the backend would ignore it', () => {
    render(<InputBar onSubmit={vi.fn()} slashCommands={slashCommands} skills={skills} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    // Only the first content line selects a skill, so no picker below it.
    fireEvent.change(input, { target: { value: 'Refactor this\n$work' } })
    expect(screen.queryByRole('listbox', { name: 'Skills' })).not.toBeInTheDocument()

    // An unknown name never chips, even on the first line.
    fireEvent.change(input, { target: { value: '$not-a-skill do it' } })
    expect(screen.queryByTestId('skill-chip')).not.toBeInTheDocument()
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

  it('reads one directive per message, from the first content line', () => {
    expect(findSkillDirectives('$work-writing draft it')).toEqual([
      { start: 0, end: 13, name: 'work-writing' },
    ])
    // Prices, shell variables and argument placeholders are not directives.
    expect(findSkillDirectives('it costs $5 and $ARGUMENTS stay plain')).toEqual([])
    expect(findSkillDirectives('email me@host.com$work-writing')).toEqual([])
    // Below the first content line the hook never looks.
    expect(findSkillDirectives('do this\n$work-writing')).toEqual([])
  })

  it('splits the composer quote block off without losing a byte', () => {
    const message = '> selected line\n> second line\n\n/goal ship it'
    const { quote, body } = splitQuotedContext(message)

    expect(quote).toBe('> selected line\n> second line\n\n')
    expect(body).toBe('/goal ship it')
    expect(quote + body).toBe(message)

    expect(splitQuotedContext('/goal ship it')).toEqual({
      quote: '',
      body: '/goal ship it',
    })
    // Nothing but quotes: no body to run a command from.
    expect(splitQuotedContext('> only a quote')).toEqual({
      quote: '',
      body: '> only a quote',
    })
  })

  it('treats only a leading, known command as a command', () => {
    expect(findCommandDirectives('/goal Ship it')).toEqual([
      { start: 0, end: 5, name: 'goal' },
    ])
    expect(findCommandDirectives('please run /goal Ship it')).toEqual([])
    expect(findCommandDirectives('/goal Ship it', new Set(['compact']))).toEqual([])
    // Skill directives belong to the skill highlighter, not this one.
    expect(findCommandDirectives('/skill:work-writing draft it')).toEqual([])
  })

  it('recognizes nested skill directives after quoted context', () => {
    const text = '> selected context\n\n/skill:git:commit Commit this change'

    expect(findSkillDirectives(text)).toEqual([
      { start: 20, end: 37, name: 'git:commit' },
    ])
    expect(findSkillDirectives(text, new Set(['work-writing']))).toEqual([])
  })

  it('keeps the selected skill highlighted after the message is sent', () => {
    render(
      <BlockRenderer
        block={{
          id: 'user-skill',
          type: 'user',
          content: '/skill:work-writing Draft the report',
        }}
        isStreaming={false}
      />,
    )

    const chip = screen.getByTestId('skill-chip')
    expect(chip).toHaveTextContent('/skill:work-writing')
    expect(chip).toHaveClass('font-semibold')
  })

  it('renders a sent $ directive as the same chip', () => {
    render(
      <BlockRenderer
        block={{ id: 'user-dollar', type: 'user', content: '$work-writing Draft the report' }}
        isStreaming={false}
      />,
    )

    expect(screen.getByTestId('skill-chip')).toHaveTextContent('$work-writing')
  })

  it('highlights built-in, workflow, and custom slash commands after send', () => {
    const { rerender } = render(
      <BlockRenderer
        block={{ id: 'user-goal', type: 'user', content: '/goal Ship the release' }}
        isStreaming={false}
      />,
    )
    expect(screen.getByTestId('command-chip')).toHaveTextContent('/goal')

    rerender(
      <BlockRenderer
        block={{ id: 'user-workflow', type: 'user', content: '/workflow release-check' }}
        isStreaming={false}
      />,
    )
    expect(screen.getByTestId('command-chip')).toHaveTextContent('/workflow')

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
