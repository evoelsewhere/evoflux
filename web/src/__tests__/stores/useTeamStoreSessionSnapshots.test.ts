/**
 * Returning to a session paints from memory.
 *
 * The store keeps one session's fields flat, so a switch used to wipe
 * them and refetch the whole transcript — measured at 368 KB and ~280 ms
 * for a long session, with a loading skeleton in between, every single
 * time. The fields of the session being left are now put aside and
 * restored on return.
 *
 * Restoring is for paint only. `loadSession` still runs and is still
 * authoritative, because a turn can finish while you are away and the
 * stream's replay covers only the current turn. What changes is that the
 * reconcile happens behind visible content instead of a blank screen —
 * which is what the skeleton condition (no blocks at all) keys off.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import { forgetSessionSnapshot, useTeamStore } from '@/stores/useTeamStore'
import { createDefaultAgentStream } from '@/stores/useTeamStore/defaults'
import type { ContentBlock } from '@/api/types'

const store = () => useTeamStore.getState()

const textBlock = (text: string): ContentBlock =>
  ({ type: 'text', text }) as ContentBlock

/** Put a session on screen with some transcript, as a load would. */
function seedSession(sessionId: string, text: string): void {
  store().beginResolvedSession(sessionId, {})
  useTeamStore.setState((state) => {
    state.leadName = 'lead'
    state.agentNames = ['lead']
    state.activeAgent = 'lead'
    state.agentStreams.lead = {
      ...createDefaultAgentStream(),
      blocks: [textBlock(text)],
    }
    state.sessionTitle = `title:${sessionId}`
  })
}

describe('session snapshots', () => {
  beforeEach(() => {
    for (const id of ['s1', 's2', 's3', 's4', 's5', 's6', 's7']) {
      forgetSessionSnapshot(id)
    }
    store().beginResolvedSession(null, {})
  })

  it('brings a transcript back without a fetch', () => {
    seedSession('s1', 'hello from s1')
    store().beginResolvedSession('s2', {})

    // s2 is new: nothing to paint, which is when a skeleton is correct.
    expect(store().agentStreams.lead?.blocks ?? []).toHaveLength(0)
    expect(store()._restoredFromCache).toBe(false)

    store().beginResolvedSession('s1', {})
    expect(store()._restoredFromCache).toBe(true)
    expect(store().agentStreams.lead?.blocks).toEqual([textBlock('hello from s1')])
    expect(store().sessionTitle).toBe('title:s1')
  })

  it('keeps each session transcript apart', () => {
    seedSession('s1', 'one')
    seedSession('s2', 'two')

    store().beginResolvedSession('s1', {})
    expect(store().agentStreams.lead?.blocks).toEqual([textBlock('one')])
    store().beginResolvedSession('s2', {})
    expect(store().agentStreams.lead?.blocks).toEqual([textBlock('two')])
  })

  it('still points at the session it was asked for', () => {
    seedSession('s1', 'one')
    store().beginResolvedSession('s2', {})
    store().beginResolvedSession('s1', {})
    expect(store().sessionId).toBe('s1')
  })

  it('bumps the generation so a stale reply cannot land', () => {
    seedSession('s1', 'one')
    const before = store()._sessionGeneration
    store().beginResolvedSession('s2', {})
    store().beginResolvedSession('s1', {})
    expect(store()._sessionGeneration).toBeGreaterThan(before)
  })

  it('forgets the least recently visited beyond the limit', () => {
    // The limit is 6; a snapshot holds a whole transcript.
    for (const id of ['s1', 's2', 's3', 's4', 's5', 's6', 's7']) {
      seedSession(id, `text:${id}`)
    }
    // Leaving s7 stashes it, evicting s1 — the oldest.
    store().beginResolvedSession('s2', {})
    expect(store()._restoredFromCache).toBe(true)

    store().beginResolvedSession('s1', {})
    expect(store()._restoredFromCache).toBe(false)
  })

  it('treats a revisit as recent use, not eviction fodder', () => {
    for (const id of ['s1', 's2', 's3', 's4', 's5', 's6']) {
      seedSession(id, `text:${id}`)
    }
    // Touch s1 so it is no longer the oldest, then push the cache over.
    store().beginResolvedSession('s1', {})
    expect(store()._restoredFromCache).toBe(true)
    seedSession('s7', 'text:s7')

    store().beginResolvedSession('s1', {})
    expect(store()._restoredFromCache).toBe(true)
  })

  it('drops a snapshot on request', () => {
    seedSession('s1', 'one')
    store().beginResolvedSession('s2', {})
    forgetSessionSnapshot('s1')

    store().beginResolvedSession('s1', {})
    expect(store()._restoredFromCache).toBe(false)
    expect(store().agentStreams.lead?.blocks ?? []).toHaveLength(0)
  })

  it('does not carry connection state across a switch', () => {
    seedSession('s1', 'one')
    useTeamStore.setState((state) => {
      state.isConnected = true
      state.isSessionLoading = true
    })
    store().beginResolvedSession('s2', {})
    store().beginResolvedSession('s1', {})

    // Whether we are attached is about now, not about what was stashed.
    expect(store().isConnected).toBe(false)
    expect(store().isSessionLoading).toBe(false)
    expect(store()._abortController).toBeNull()
  })
})
