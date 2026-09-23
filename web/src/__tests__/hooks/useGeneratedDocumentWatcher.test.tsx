import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useGeneratedDocumentWatcher } from '@/hooks/useGeneratedDocumentWatcher'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { queryKeys } from '@/queries/keys'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  listeners = new Map<string, (event: MessageEvent<string>) => void>()
  closed = false
  url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  addEventListener(name: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(name, listener)
  }
  removeEventListener(name: string) {
    this.listeners.delete(name)
  }
  close() {
    this.closed = true
  }
  emit(changes: Array<{ type: string; path: string }>) {
    this.listeners.get('fs_change')?.({ data: JSON.stringify(changes) } as MessageEvent<string>)
  }
}

function setup(sessionId = 'session-1') {
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const hook = renderHook(() => useGeneratedDocumentWatcher(sessionId), { wrapper })
  return { hook, invalidate, source: FakeEventSource.instances.at(-1)! }
}

let requestWorkspaceFile = vi.fn<(sessionId: string, path: string) => void>()

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  window.localStorage.removeItem(STORAGE_KEYS.autoOpenGeneratedDocuments)
  requestWorkspaceFile = vi.fn<(sessionId: string, path: string) => void>()
  useUIStore.setState({ workbenchOpen: false, activeWorkbenchTool: null, requestWorkspaceFile })
  useTeamStore.setState({ sessionId: 'session-1', isTeamWorking: true })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useGeneratedDocumentWatcher', () => {
  it('watches the session workspace and refreshes files on Office saves', () => {
    const { source, invalidate } = setup()

    expect(source.url).toContain('/team/session-1/files/watch')
    source.emit([{ type: 'modified', path: 'notes.md' }])
    expect(invalidate).not.toHaveBeenCalled()
    source.emit([{ type: 'modified', path: 'decks/review.pptx' }])
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.team.files('session-1') })
  })

  it('opens the preview of a deck the agent just created, once', () => {
    const { source } = setup()

    source.emit([{ type: 'added', path: 'review.pptx' }])
    source.emit([{ type: 'added', path: 'review.pptx' }])

    expect(requestWorkspaceFile).toHaveBeenCalledTimes(1)
    expect(requestWorkspaceFile).toHaveBeenCalledWith('session-1', 'review.pptx')
  })

  it('does not open anything when no turn is running', () => {
    useTeamStore.setState({ isTeamWorking: false })
    const { source } = setup()

    source.emit([{ type: 'added', path: 'review.pptx' }])

    expect(requestWorkspaceFile).not.toHaveBeenCalled()
  })

  it('leaves another open workbench tool alone', () => {
    useUIStore.setState({ workbenchOpen: true, activeWorkbenchTool: 'terminal' })
    const { source } = setup()

    source.emit([{ type: 'added', path: 'review.pptx' }])

    expect(requestWorkspaceFile).not.toHaveBeenCalled()
  })

  it('respects the opt-out preference', () => {
    window.localStorage.setItem(STORAGE_KEYS.autoOpenGeneratedDocuments, 'false')
    const { source } = setup()

    source.emit([{ type: 'added', path: 'report.docx' }])

    expect(requestWorkspaceFile).not.toHaveBeenCalled()
  })

  it('closes the stream when the session goes away', () => {
    const { hook, source } = setup()

    hook.unmount()

    expect(source.closed).toBe(true)
  })
})
