import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createSkillRecordingChatFiles,
  createSkillRecordingChatPrompt,
  createSkillRecordingChatFile,
  consumeSkillRecordingChatHandoff,
  clearCachedSkillRecordingChatHandoff,
  loadCachedSkillRecordingChatHandoff,
  stageSkillRecordingChatHandoff,
  subscribeSkillRecordingChatHandoff,
} from '@/lib/skill-recording-chat'

const CACHE_KEY = 'evoflux:skill-recording-chat-handoff'
function createStorage() {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value) },
    removeItem: (key: string) => { values.delete(key) },
  }
}

describe('skill recording chat handoff', () => {
  afterEach(() => {
    consumeSkillRecordingChatHandoff()
    clearCachedSkillRecordingChatHandoff()
  })

  it('keeps the reviewed trace local until the chat composer consumes it once', () => {
    const handoff = {
      recordingId: 'record-1',
      payload: '{"goal":"","events":[{"sequence":1,"kind":"invoked"}]}',
    }

    stageSkillRecordingChatHandoff(handoff)

    expect(consumeSkillRecordingChatHandoff()).toEqual(handoff)
    expect(consumeSkillRecordingChatHandoff()).toBeNull()
  })

  it('notifies an already mounted chat when a reviewed trace is staged', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeSkillRecordingChatHandoff(listener)

    stageSkillRecordingChatHandoff({ recordingId: 'record-2', payload: '{"events":[]}' })

    expect(listener).toHaveBeenCalledOnce()
    unsubscribe()
  })

  it('keeps the reviewed trace in local cache for one hour for later reuse', () => {
    const handoff = { recordingId: 'record-cache', payload: '{"events":[]}' }
    const now = 1_800_000_000_000
    const storage = createStorage()

    stageSkillRecordingChatHandoff(handoff, { now, storage })

    expect(loadCachedSkillRecordingChatHandoff({ now: now + 59 * 60_000, storage })).toEqual(handoff)
    expect(loadCachedSkillRecordingChatHandoff({ now: now + 60 * 60_000, storage })).toBeNull()
    expect(storage.getItem(CACHE_KEY)).toBeNull()
  })

  it('drops malformed cached handoffs without failing chat startup', () => {
    const storage = createStorage()
    storage.setItem(CACHE_KEY, '{broken')

    expect(loadCachedSkillRecordingChatHandoff({ storage })).toBeNull()
    expect(storage.getItem(CACHE_KEY)).toBeNull()
  })

  it('creates a JSON attachment containing the reviewed trace', async () => {
    const handoff = { recordingId: 'record-3', payload: '{"events":[{"sequence":1}]}' }
    const file = createSkillRecordingChatFile(handoff)

    expect(file.name).toBe('skill-demo-trace.json')
    expect(file.type).toMatch(/^application\/json(?:;|$)/)
    expect(await file.text()).toBe(handoff.payload)
  })

  it('loads selected screen evidence as image attachments for the chat model', async () => {
    const handoff = {
      recordingId: 'record-4',
      payload: JSON.stringify({
        goal: 'Search for a cited article',
        events: [
          {
            sequence: 1,
            elapsed_ms: 1200,
            kind: 'click',
            button: 'left',
            point: { x: 10, y: 20 },
            target: { control_type: 'button', name: 'Search', automation_id: null },
            value_state: 'not_captured',
            value: null,
            screenshot: null,
          },
          {
            sequence: 2,
            elapsed_ms: 1450,
            kind: 'value_changed',
            window: { app: 'browser.exe', title: 'Article page' },
            target: { control_type: 'Edit', label: 'Search query', name: null },
            value_state: 'captured',
            value: 'international news',
            screenshot: null,
          },
          {
            sequence: 3,
            elapsed_ms: 1201,
            kind: 'screenshot',
            target: { control_type: 'screen frame', name: 'After left click at (10, 20)', automation_id: null },
            value_state: 'not_captured',
            value: null,
            screenshot: 'screenshots/000003.png',
          },
        ],
      }),
      screenshotSequences: [3],
    }
    const fetchImage = vi.fn().mockResolvedValue(
      new Response('png-bytes', { status: 200, headers: { 'Content-Type': 'image/png' } }),
    )

    const files = await createSkillRecordingChatFiles(handoff, fetchImage)

    expect(fetchImage).toHaveBeenCalledWith('/api/skill-recordings/record-4/screenshots/3')
    expect(files).toHaveLength(3)
    expect(files[0].name).toBe('skill-demo-trace.json')
    expect(files[1].name).toBe('skill-demo-context.md')
    const context = await files[1].text()
    expect(context).toContain('Event 1. [1.2s] Click (left) at (10, 20) — button: Search')
    expect(context).toContain('Event 2. [1.4s] Input changed — Edit: Search query [browser.exe — Article page]; reviewed input: international news')
    expect(context).toContain('skill-demo-frame-000003.png')
    expect(context).toContain('Coverage limits:')
    expect(files[2].name).toBe('skill-demo-frame-000003.png')
    expect(files[2].type).toBe('image/png')
    expect(await files[2].text()).toBe('png-bytes')
    expect(createSkillRecordingChatPrompt(handoff)).toContain('- skill-demo-frame-000003.png')
  })
})
