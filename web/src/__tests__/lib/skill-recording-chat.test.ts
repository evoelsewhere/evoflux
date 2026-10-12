import { afterEach, describe, expect, it, vi } from 'vitest'

import {
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

  it('creates a JSON attachment containing only the reviewed trace', async () => {
    const handoff = { recordingId: 'record-3', payload: '{"events":[{"sequence":1}]}' }
    const file = createSkillRecordingChatFile(handoff)

    expect(file.name).toBe('skill-demo-trace.json')
    expect(file.type).toMatch(/^application\/json(?:;|$)/)
    expect(await file.text()).toBe(handoff.payload)
  })
})
