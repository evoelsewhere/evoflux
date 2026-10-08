import { beforeEach, describe, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'

const mocks = vi.hoisted(() => ({
  getCurrent: vi.fn(),
  onOpenUrl: vi.fn(),
  show: vi.fn(),
  unminimize: vi.fn(),
  setFocus: vi.fn(),
  handler: undefined as ((urls: string[]) => void) | undefined,
}))

vi.mock('@tauri-apps/plugin-deep-link', () => ({
  getCurrent: mocks.getCurrent,
  onOpenUrl: mocks.onOpenUrl,
}))

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({
    show: mocks.show,
    unminimize: mocks.unminimize,
    setFocus: mocks.setFocus,
  }),
}))

import {
  parseNotificationUrl,
  routeForActivation,
  startNotificationActivation,
  type NotificationActivation,
} from '@/lib/notification-activation'

const sessionId = '00000000-0000-4000-8000-000000000001'
const requestId = '00000000-0000-4000-8000-000000000002'
const focusId = '00000000-0000-4000-8000-000000000003'
const workUrl = `evoflux://notification?v=1&mode=work&session_id=${sessionId}&event_kind=question_asked&request_id=${requestId}`

const codingActivation: NotificationActivation = {
  version: 1,
  mode: 'coding',
  sessionId,
  focusId,
  eventKind: 'question_asked',
  requestId,
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.handler = undefined
  mocks.getCurrent.mockResolvedValue(null)
  mocks.onOpenUrl.mockImplementation(async (handler: (urls: string[]) => void) => {
    mocks.handler = handler
    return vi.fn()
  })
  mocks.show.mockResolvedValue(undefined)
  mocks.unminimize.mockResolvedValue(undefined)
  mocks.setFocus.mockResolvedValue(undefined)
})

describe('notification activation URLs', () => {
  it('accepts a valid Work activation and rejects external URLs', () => {
    const url = `evoflux://notification?v=1&mode=work&session_id=${sessionId}&event_kind=question_asked&request_id=${requestId}`

    expect(parseNotificationUrl(url)?.sessionId).toBe(sessionId)
    expect(parseNotificationUrl('https://example.com')).toBeNull()
  })

  it('builds a Coding session route and rejects duplicate query keys', () => {
    expect(routeForActivation(codingActivation)).toEqual({
      to: '/coding/$focusId/$sessionId',
      params: { focusId, sessionId },
    })
    expect(
      parseNotificationUrl(
        `evoflux://notification?v=1&mode=work&mode=coding&session_id=${sessionId}&event_kind=question_asked`,
      ),
    ).toBeNull()
  })

  it('accepts known development schemes and rejects malformed or unknown fields', () => {
    const suffix = `?v=1&mode=work&session_id=${sessionId}&event_kind=assistant_done`
    expect(parseNotificationUrl(`evoflux-dev://notification${suffix}`)?.mode).toBe('work')
    expect(parseNotificationUrl(`evoflux-dev-bundled://notification${suffix}`)?.mode).toBe('work')
    expect(parseNotificationUrl(`evoflux-other://notification${suffix}`)).toBeNull()
    expect(parseNotificationUrl(`evoflux://other${suffix}`)).toBeNull()
    expect(parseNotificationUrl(`evoflux://notification${suffix}&extra=value`)).toBeNull()
    expect(parseNotificationUrl(`evoflux://notification${suffix}&input=%E0%A4%A`)).toBeNull()
  })

  it('requires UUID session and Coding focus IDs', () => {
    expect(parseNotificationUrl('evoflux://notification?v=1&mode=work&session_id=s1&event_kind=question_asked')).toBeNull()
    expect(
      parseNotificationUrl(
        `evoflux://notification?v=1&mode=coding&session_id=${sessionId}&event_kind=question_asked&focus_id=folder`,
      ),
    ).toBeNull()
    expect(
      parseNotificationUrl(
        `evoflux://notification?v=1&mode=work&session_id=${sessionId}&event_kind=question_asked&focus_id=${focusId}`,
      ),
    ).toBeNull()
  })

  it('accepts bounded single-answer input only for answer actions', () => {
    const prefix = `evoflux://notification?v=1&mode=work&session_id=${sessionId}&event_kind=question_asked&request_id=${requestId}`
    const answer = 'approve this action'

    expect(parseNotificationUrl(`${prefix}&action_id=answer&input=${encodeURIComponent(answer)}`)?.input).toBe(answer)
    expect(parseNotificationUrl(`${prefix}&action_id=permission-once&input=yes`)).toBeNull()
    expect(parseNotificationUrl(`${prefix}&action_id=answer&input=${'a'.repeat(2049)}`)).toBeNull()
    expect(parseNotificationUrl(`${prefix}&action_id=answer&input=line%0Abreak`)).toBeNull()
  })

  it('rejects unknown event and action kinds, missing gate IDs, and oversized URLs', () => {
    expect(
      parseNotificationUrl(
        `evoflux://notification?v=1&mode=work&session_id=${sessionId}&event_kind=agent_status`,
      ),
    ).toBeNull()
    expect(
      parseNotificationUrl(
        `evoflux://notification?v=1&mode=work&session_id=${sessionId}&event_kind=question_asked`,
      ),
    ).toBeNull()
    expect(
      parseNotificationUrl(
        `evoflux://notification?v=1&mode=work&session_id=${sessionId}&event_kind=assistant_done&action_id=execute`,
      ),
    ).toBeNull()
    expect(parseNotificationUrl(`evoflux://notification?${'x'.repeat(4096)}`)).toBeNull()
  })

  it('routes a cold-start URL once after installing the listener', async () => {
    mocks.getCurrent.mockResolvedValue([workUrl])
    const navigate = vi.fn().mockResolvedValue(undefined)

    await startNotificationActivation({ navigate })

    expect(mocks.onOpenUrl).toHaveBeenCalledTimes(1)
    expect(mocks.getCurrent).toHaveBeenCalledTimes(1)
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(navigate).toHaveBeenCalledWith({
      to: '/$sessionId',
      params: { sessionId },
    })
    expect(mocks.show).toHaveBeenCalledTimes(1)
    expect(mocks.unminimize).toHaveBeenCalledTimes(1)
    expect(mocks.setFocus).toHaveBeenCalledTimes(1)
  })

  it('routes a running-app Coding URL and deduplicates a repeated activation', async () => {
    const navigate = vi.fn().mockResolvedValue(undefined)
    await startNotificationActivation({ navigate })
    const url = `evoflux://notification?v=1&mode=coding&session_id=${sessionId}&focus_id=${focusId}&event_kind=question_asked&request_id=${requestId}`

    mocks.handler?.([url, url])
    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1))

    expect(navigate).toHaveBeenCalledWith({
      to: '/coding/$focusId/$sessionId',
      params: { focusId, sessionId },
    })
  })
})
