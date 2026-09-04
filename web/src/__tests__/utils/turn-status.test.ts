import { describe, expect, it } from 'vitest'

import { activeToolLabel, liveTurnActivity } from '@/utils/turn-status'
import type { ContentBlock } from '@/api/types'

function block(partial: Partial<ContentBlock> & Pick<ContentBlock, 'type'>): ContentBlock {
  return {
    id: partial.id ?? Math.random().toString(36).slice(2),
    content: '',
    ...partial,
  } as ContentBlock
}

describe('activeToolLabel', () => {
  it('names the file a write tool is working on, by basename', () => {
    expect(activeToolLabel('edit', JSON.stringify({ file_path: 'desktop/src-tauri/src/main.rs' })))
      .toBe('Editing main.rs')
  })

  it('prints the command for a shell call', () => {
    expect(activeToolLabel('shell', JSON.stringify({ command: 'git status' })))
      .toBe('Running git status')
  })

  it('falls back to the verb alone when no argument is worth naming', () => {
    expect(activeToolLabel('read', undefined)).toBe('Reading…')
  })

  it('names an unknown tool rather than guessing a verb', () => {
    expect(activeToolLabel('acme_thing', JSON.stringify({ query: 'widgets' })))
      .toBe('Running acme_thing · widgets')
  })

  it('truncates a long argument', () => {
    const label = activeToolLabel('grep', JSON.stringify({ pattern: 'x'.repeat(120) }))
    expect(label.length).toBeLessThan(60)
    expect(label.endsWith('…')).toBe(true)
  })
})

describe('liveTurnActivity', () => {
  it('reports the running tool while a call is open', () => {
    const activity = liveTurnActivity(
      [block({ type: 'tool', toolName: 'edit', toolArgs: '{"file_path":"main.rs"}' })],
      'model_calling',
      'opus-5',
    )
    expect(activity).toEqual({ kind: 'tool', label: 'Editing main.rs', toolName: 'edit' })
  })

  it('waits on the model once a tool call has finished', () => {
    // The backend emits `model_calling` once per turn, so the phase cannot
    // tell us this — only the block tail can.
    const activity = liveTurnActivity(
      [block({ type: 'tool', toolName: 'edit', toolDone: true })],
      'model_calling',
      'opus-5',
    )
    expect(activity.kind).toBe('waiting')
    expect(activity.label).toBe('Waiting for opus-5…')
  })

  it('distinguishes reasoning from answering', () => {
    expect(liveTurnActivity([block({ type: 'thinking' })], 'model_calling', null).kind)
      .toBe('thinking')
    expect(liveTurnActivity([block({ type: 'text' })], 'model_calling', null).kind)
      .toBe('responding')
  })

  it('separates ingress from a request the provider already has', () => {
    expect(liveTurnActivity([], 'ingress', 'opus-5').kind).toBe('preparing')
    expect(liveTurnActivity([], null, 'opus-5').kind).toBe('preparing')
    expect(liveTurnActivity([], 'model_calling', 'opus-5').kind).toBe('waiting')
  })

  it('ignores the user block a turn opens with', () => {
    const activity = liveTurnActivity(
      [block({ type: 'user', content: 'hi' })],
      'model_calling',
      'opus-5',
    )
    expect(activity.kind).toBe('waiting')
  })

  it('names no model rather than inventing one', () => {
    expect(liveTurnActivity([], 'model_calling', null).label).toBe('Waiting for the model…')
  })
})
