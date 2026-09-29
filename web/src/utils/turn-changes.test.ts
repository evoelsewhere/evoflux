import { describe, expect, it } from 'vitest'

import type { MessageResponse } from '@/api/types'
import { parseTurnChanges, turnChangesFromHistory } from './turn-changes'

const saved = {
  session_id: 'session-1',
  additions: 2,
  deletions: 0,
  files: [{ path: 'src/util.ts', status: 'added', additions: 2, deletions: 0 }],
}

function message(role: string, extra: Record<string, unknown> | null = null): MessageResponse {
  return { id: `${role}-${Math.random()}`, role, content: '', extra } as unknown as MessageResponse
}

describe('parseTurnChanges', () => {
  it('reads the live event and the saved copy alike', () => {
    expect(parseTurnChanges('fallback', saved)).toEqual({
      sessionId: 'session-1',
      additions: 2,
      deletions: 0,
      files: [{ path: 'src/util.ts', status: 'added', additions: 2, deletions: 0 }],
    })
  })

  it('treats a turn that changed nothing as no summary', () => {
    expect(parseTurnChanges('s', { files: [] })).toBeNull()
    expect(parseTurnChanges('s', null)).toBeNull()
  })
})

describe('turnChangesFromHistory', () => {
  it('restores the latest turn summary after a reload', () => {
    const messages = [message('user', { turn_changes: saved }), message('assistant')]
    expect(turnChangesFromHistory('session-1', messages)?.files).toHaveLength(1)
  })

  it('shows nothing when the latest turn changed nothing', () => {
    // An older turn's files are not what the latest turn did.
    const messages = [
      message('user', { turn_changes: saved }),
      message('assistant'),
      message('user', {}),
      message('assistant'),
    ]
    expect(turnChangesFromHistory('session-1', messages)).toBeNull()
  })

  it('skips a queued message that has not started its turn', () => {
    const messages = [
      message('user', { turn_changes: saved }),
      message('assistant'),
      message('user', { queue_status: 'queued' }),
    ]
    expect(turnChangesFromHistory('session-1', messages)?.files[0]?.path).toBe('src/util.ts')
  })
})
