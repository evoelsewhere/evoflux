import {
  getPendingPermissions,
  getPendingQuestions,
  replyAskUserQuestion,
  replyPermissionRequest,
} from '@/api/client/team'
import type { NotificationActivation } from '@/lib/notification-activation'

export type NotificationActionResult = 'replied' | 'stale' | 'open-session'

function isNotFoundError(error: unknown): boolean {
  return error instanceof Error && /\b404\b/.test(error.message)
}

/**
 * Apply only narrow notification actions after re-reading the pending gate.
 * Complex forms, stale requests and implicit grants always return to the app.
 */
export async function handleNotificationAction(
  activation: NotificationActivation,
): Promise<NotificationActionResult> {
  const { actionId, requestId, sessionId } = activation
  if (!actionId || actionId === 'open') return 'open-session'
  if (!requestId) return 'stale'

  if (activation.eventKind === 'question_asked') {
    const pending = await getPendingQuestions(sessionId)
    const request = pending.questions.find((item) => item.request_id === requestId)
    if (!request || request.items.length !== 1) return 'stale'
    const item = request.items[0]
    let answer: string

    if (actionId === 'answer') {
      if (item.kind === 'agent_spawn' || typeof activation.input !== 'string' || activation.input.length > 2048) {
        return 'open-session'
      }
      answer = activation.input
    } else if (actionId === 'choice') {
      if (item.kind === 'agent_spawn' || typeof activation.input !== 'string' || !item.options.includes(activation.input)) {
        return 'open-session'
      }
      answer = activation.input
    } else if (actionId === 'spawn-defaults') {
      const defaults = item.agent_spawn
      if (item.kind !== 'agent_spawn' || !defaults?.blueprint || !defaults.default_model.trim()) {
        return 'open-session'
      }
      answer = JSON.stringify({
        model: defaults.default_model,
        thinking_level: defaults.default_thinking_level ?? null,
      })
    } else {
      return 'open-session'
    }

    try {
      await replyAskUserQuestion(request.session_id || sessionId, requestId, [answer])
      return 'replied'
    } catch (error) {
      if (isNotFoundError(error)) return 'stale'
      throw error
    }
  }

  if (activation.eventKind === 'permission_asked') {
    if (actionId !== 'permission-once' && actionId !== 'permission-reject') return 'open-session'
    const pending = await getPendingPermissions(sessionId)
    const permission = pending.permissions.find((item) => item.id === requestId)
    if (!permission) return 'stale'
    try {
      await replyPermissionRequest(
        permission.session_id || sessionId,
        requestId,
        actionId === 'permission-once' ? 'once' : 'reject',
      )
      return 'replied'
    } catch (error) {
      if (isNotFoundError(error)) return 'stale'
      throw error
    }
  }

  return 'open-session'
}
