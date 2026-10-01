import { isSessionId } from '@/lib/mode-route'
import { isProjectFocusId } from '@/utils/workspace'
import { markInboxNotificationReadByActivation } from '@/lib/notification-inbox'

/**
 * Notification activation URL parsing and routing.
 *
 * Parses ``evoflux://notification`` deep-links from desktop notifications
 * and converts them into internal route objects.
 *
 * URL format (all query params except ``v`` are required unless noted):
 *
 *   evoflux://notification?v=1&mode=work|coding&session_id=<uuid>
 *     &event_kind=<known notification event>
 *     &request_id=<uuid>           (required for question_asked)
 *     &focus_id=<uuid>             (required for coding mode)
 *     &action_id=open|answer|choice|spawn-defaults|permission-once|permission-reject (optional)
 *     &input=<text>                (only with action_id=answer, max 2048 chars, single line)
 */

// ── Types ───────────────────────────────────────────────────────────────────

interface ActivationBase {
  version: 1
  sessionId: string
  eventKind: NotificationEventKind
  requestId?: string
  focusId?: string
  actionId?: NotificationActionId
  input?: string
  actions?: Array<{ id: string; label: string; input?: string }>
}

export type NotificationActivation = ActivationBase & (
  | { mode: 'work'; focusId?: never }
  | { mode: 'coding'; focusId: string }
)

export type ActivationRoute =
  | { to: '/$sessionId'; params: { sessionId: string } }
  | { to: '/coding/$focusId/$sessionId'; params: { focusId: string; sessionId: string } }

export type NotificationEventKind =
  | 'question_asked'
  | 'permission_asked'
  | 'agent_not_configured'
  | 'terminal_error'
  | 'goal_blocked'
  | 'assistant_done'
  | 'background_done'
  | 'reminder_fired'

type NotificationActionId =
  | 'open'
  | 'answer'
  | 'choice'
  | 'spawn-defaults'
  | 'permission-once'
  | 'permission-reject'

export type NotificationActivationAction = { id: string; label: string; input?: string }

interface ActivationRouter {
  navigate: (route: ActivationRoute) => unknown
}

type ActivationHandler = (activation: NotificationActivation) => Promise<void>

// ── Constants ───────────────────────────────────────────────────────────────

const ALLOWED_SCHEMES = new Set(['evoflux', 'evoflux-dev', 'evoflux-dev-bundled'])
const ALLOWED_MODES = new Set(['work', 'coding'])
const ALLOWED_EVENT_KINDS = new Set<NotificationEventKind>([
  'question_asked',
  'permission_asked',
  'agent_not_configured',
  'terminal_error',
  'goal_blocked',
  'assistant_done',
  'background_done',
  'reminder_fired',
])
const ALLOWED_ACTION_IDS = new Set<NotificationActionId>([
  'open',
  'answer',
  'choice',
  'spawn-defaults',
  'permission-once',
  'permission-reject',
])

// UUID_RE removed — validation uses isSessionId() and isProjectFocusId() instead.
const MAX_URL_LENGTH = 4096
const MAX_INPUT_BYTES = 2048
const SAFE_REQUEST_ID_RE = /^[A-Za-z0-9_-]{1,128}$/
// eslint-disable-next-line no-control-regex
const CONTROL_CHARACTER_RE = /[\x00-\x1f\x7f]/

/** Fields that are allowed in the query string (used to reject unknown keys). */
const ALLOWED_PARAMS = new Set([
  'v',
  'mode',
  'session_id',
  'event_kind',
  'request_id',
  'focus_id',
  'action_id',
  'input',
])

// ── Public API ──────────────────────────────────────────────────────────────

/**
 * Parse an ``evoflux://notification`` URL into an activation descriptor.
 *
 * Returns ``null`` if the URL is malformed, contains unknown fields,
 * has duplicate query keys, fails UUID validation, or violates any
 * constraint documented in the module header.
 */
export function parseNotificationUrl(url: string): NotificationActivation | null {
  // Reject oversized URLs early.
  if (!url || url.length > MAX_URL_LENGTH || CONTROL_CHARACTER_RE.test(url)) return null

  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }

  // ── Scheme ───────────────────────────────────────────────────────────
  if (!ALLOWED_SCHEMES.has(parsed.protocol.replace(':', ''))) return null

  // ── Path ─────────────────────────────────────────────────────────────
  if (
    parsed.hostname !== 'notification'
    || parsed.pathname !== ''
    || parsed.port !== ''
    || parsed.username !== ''
    || parsed.password !== ''
    || parsed.hash !== ''
  ) return null

  // ── Duplicate-key / unknown-key guard ────────────────────────────────
  // ``URLSearchParams`` silently deduplicates, so we count raw pairs first.
  const rawPairs = parsed.search ? parsed.search.slice(1).split('&') : []
  const seenKeys = new Set<string>()
  for (const pair of rawPairs) {
    const eqIdx = pair.indexOf('=')
    const key = eqIdx === -1 ? pair : pair.slice(0, eqIdx)
    const value = eqIdx === -1 ? '' : pair.slice(eqIdx + 1)
    const decodedKey = tryDecode(key.replaceAll('+', ' '))
    const decodedValue = tryDecode(value.replaceAll('+', ' '))
    if (decodedKey === null || decodedValue === null) return null
    if (CONTROL_CHARACTER_RE.test(decodedKey) || CONTROL_CHARACTER_RE.test(decodedValue)) return null
    if (seenKeys.has(decodedKey)) return null // duplicate
    if (!ALLOWED_PARAMS.has(decodedKey)) return null // unknown
    seenKeys.add(decodedKey)
  }

  const sp = parsed.searchParams

  // ── Required fields ──────────────────────────────────────────────────
  const versionStr = sp.get('v')
  if (!versionStr) return null
  if (versionStr !== '1') return null
  const version = 1 as const

  const mode = sp.get('mode')
  if (!mode || !ALLOWED_MODES.has(mode)) return null

  const sessionId = sp.get('session_id')
  if (!sessionId || !isSessionId(sessionId)) return null

  const eventKind = sp.get('event_kind') as NotificationEventKind | null
  if (!eventKind || !ALLOWED_EVENT_KINDS.has(eventKind)) return null

  // ── Conditional required fields ──────────────────────────────────────
  const requestId = sp.get('request_id') ?? undefined
  if ((eventKind === 'question_asked' || eventKind === 'permission_asked') && !requestId) return null
  if (requestId && !SAFE_REQUEST_ID_RE.test(requestId)) return null

  const focusId = sp.get('focus_id') ?? undefined
  if (mode === 'coding' && (!focusId || !isProjectFocusId(focusId))) return null
  // Work mode must NOT have a focus_id.
  if (mode === 'work' && focusId) return null

  // ── Action fields ────────────────────────────────────────────────────
  const actionId = sp.get('action_id') ?? undefined
  if (actionId && !ALLOWED_ACTION_IDS.has(actionId as NotificationActionId)) return null
  if (actionId && !actionMatchesEvent(actionId as NotificationActionId, eventKind as NotificationEventKind)) return null
  if (actionId && actionId !== 'open' && !requestId) return null

  const input = sp.get('input') ?? undefined
  if (input !== undefined) {
    // Text and choice replies are the only actions allowed to carry input.
    if (actionId !== 'answer' && actionId !== 'choice') return null
    if (input.length === 0 || new TextEncoder().encode(input).byteLength > MAX_INPUT_BYTES) return null
  } else if (actionId === 'choice') {
    return null
  }

  return {
    version,
    mode: mode as 'work' | 'coding',
    sessionId,
    eventKind: eventKind as NotificationEventKind,
    ...(requestId ? { requestId } : {}),
    ...(mode === 'coding' ? { focusId } : {}),
    ...(actionId ? { actionId: actionId as NotificationActionId } : {}),
    ...(input !== undefined ? { input } : {}),
  } as NotificationActivation
}

/**
 * Convert a parsed activation descriptor into a TanStack Router route object.
 */
export function routeForActivation(activation: NotificationActivation): ActivationRoute {
  if (activation.mode === 'coding') {
    return {
      to: '/coding/$focusId/$sessionId',
      params: { focusId: activation.focusId as string, sessionId: activation.sessionId },
    }
  }

  // Work mode
  return {
    to: '/$sessionId',
    params: { sessionId: activation.sessionId },
  }
}

/** Build a validated notification target from the currently open session route. */
export function createNotificationActivation(
  eventKind: NotificationEventKind,
  sessionId: string,
  requestId?: string,
  actions?: NotificationActivationAction[],
): NotificationActivation | undefined {
  if (!isSessionId(sessionId)) return undefined
  if ((eventKind === 'question_asked' || eventKind === 'permission_asked') && !requestId) return undefined
  if (requestId && !SAFE_REQUEST_ID_RE.test(requestId)) return undefined

  const segments = window.location.pathname.split('/').filter(Boolean)
  if (segments[0] === 'coding') {
    const focusId = segments[1]
    if (!focusId || !isProjectFocusId(focusId)) return undefined
    return {
      version: 1,
      mode: 'coding',
      focusId,
      sessionId,
      eventKind,
      ...(requestId ? { requestId } : {}),
      ...(actions?.length ? { actions } : {}),
    }
  }
  return {
    version: 1,
    mode: 'work',
    sessionId,
    eventKind,
    ...(requestId ? { requestId } : {}),
    ...(actions?.length ? { actions } : {}),
  }
}

/** Install the deep-link listener before reading cold-start URLs. */
export async function startNotificationActivation(
  router: ActivationRouter,
  onActivation?: ActivationHandler,
): Promise<() => void> {
  const unlisteners: Array<() => void> = []
  const seen = new Set<string>()

  const activate = async (activation: NotificationActivation) => {
    const key = JSON.stringify(activation)
    if (seen.has(key)) return
    seen.add(key)
    markInboxNotificationReadByActivation(activation)
    if (seen.size > 128) {
      const oldest = seen.values().next().value as string | undefined
      if (oldest) seen.delete(oldest)
    }

    // Complete quick actions before routing. Previously the action and route
    // listeners raced each other, while action failures were silently ignored.
    if (onActivation) await onActivation(activation)

    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window')
      const appWindow = getCurrentWindow()
      await appWindow.show()
      await appWindow.unminimize()
      await appWindow.setFocus()
    } catch {
      // Keep routing usable in browser previews where no native window exists.
    }

    await router.navigate(routeForActivation(activation))
  }

  const handleUrls = (urls: string[]) => {
    for (const url of urls) {
      const activation = parseNotificationUrl(url)
      if (activation) void activate(activation)
    }
  }

  try {
    const { getCurrent, onOpenUrl } = await import('@tauri-apps/plugin-deep-link')
    unlisteners.push(await onOpenUrl(handleUrls))
    const currentUrls = await getCurrent()
    if (currentUrls) handleUrls(currentUrls)
  } catch {
    // The browser preview may not include the native deep-link plugin.
  }

  try {
    const { listen } = await import('@tauri-apps/api/event')
    unlisteners.push(await listen<{ url?: unknown }>('notification-action-activation', (event) => {
      const url = event.payload?.url
      if (typeof url === 'string') handleUrls([url])
    }))
  } catch {
    // Native toast input is only available inside the desktop app.
  }

  return () => unlisteners.forEach((unlisten) => unlisten())
}

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Try to percent-decode a string; return ``null`` on malformed sequences. */
function tryDecode(value: string): string | null {
  try {
    return decodeURIComponent(value)
  } catch {
    return null
  }
}

function actionMatchesEvent(actionId: NotificationActionId, eventKind: NotificationEventKind): boolean {
  if (actionId === 'open') return true
  if (actionId === 'answer' || actionId === 'choice' || actionId === 'spawn-defaults') {
    return eventKind === 'question_asked'
  }
  return eventKind === 'permission_asked'
}
