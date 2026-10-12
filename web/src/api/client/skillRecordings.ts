import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'

export type SkillRecordingWindow = {
  id: number
  app: string
  title: string
  foreground: boolean
  minimized: boolean
}

export type SkillRecordingEvent = {
  sequence: number
  elapsed_ms: number
  kind:
    | 'click'
    | 'double_click'
    | 'scroll'
    | 'window_change'
    | 'focus'
    | 'invoked'
    | 'selected'
    | 'value_changed'
    | 'state_change'
    | 'window_opened'
    | 'window_closed'
    | 'gap'
    | 'screenshot'
  point?: { x: number; y: number; display_id: string | null } | null
  button?: 'left' | 'middle' | 'right' | null
  scroll_delta?: { x: number; y: number } | null
  target: { automation_id: string | null; control_type: string | null; name: string | null } | null
  value_state: 'not_captured' | 'captured' | 'omitted_secure' | 'unavailable'
  value: string | null
  screenshot: string | null
}

export type SkillRecording = {
  id: string
  status: 'recording' | 'paused' | 'stopped'
  events: SkillRecordingEvent[]
  schema_version?: number
  expires_at?: string | null
  video_artifacts?: Array<{
    id: 'video'
    path: 'video.webm'
    media_type: 'video/webm'
    byte_length: number
  }>
}

export type SkillRecordingVideoUpload = {
  recording_id: string
  artifact_id: 'video'
  media_type: 'video/webm'
  byte_length: number
  expires_at: string
}

export type SkillRecordingReview = {
  selected_event_ids: number[]
  redactions: Record<string, string>
  goal: string
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}/skill-recordings${path}`, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) await parseDetailOrThrow(response, `POST ${path}`)
  return response.json()
}

export async function createSkillRecording(): Promise<{ id: string }> {
  return post('')
}

export async function appendSkillRecordingEvents(
  id: string,
  events: SkillRecordingEvent[],
): Promise<unknown> {
  return post(`/${encodeURIComponent(id)}/events`, { events })
}

export async function setSkillRecordingState(
  id: string,
  action: 'pause' | 'resume' | 'stop',
): Promise<unknown> {
  return post(`/${encodeURIComponent(id)}/${action}`)
}

export async function uploadSkillRecordingVideo(
  id: string,
  video: Blob,
): Promise<SkillRecordingVideoUpload> {
  const response = await fetch(
    `${apiBaseUrl()}/skill-recordings/${encodeURIComponent(id)}/video`,
    {
      method: 'PUT',
      headers: { 'Content-Type': video.type || 'video/webm' },
      body: video,
    },
  )
  if (!response.ok) await parseDetailOrThrow(response, `PUT skill recording video ${id}`)
  return response.json()
}

export async function getSkillRecording(id: string): Promise<SkillRecording> {
  const response = await fetch(`${apiBaseUrl()}/skill-recordings/${encodeURIComponent(id)}`)
  if (!response.ok) await parseDetailOrThrow(response, `GET skill recording ${id}`)
  return response.json()
}

export async function deleteSkillRecording(id: string): Promise<void> {
  const response = await fetch(`${apiBaseUrl()}/skill-recordings/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!response.ok) await parseDetailOrThrow(response, `DELETE skill recording ${id}`)
}

export async function previewSkillRecordingDraft(
  id: string,
  body: SkillRecordingReview,
): Promise<{ payload: string; provider_model: string | null; sha256: string }> {
  return post(`/${encodeURIComponent(id)}/preview`, body)
}

export async function createSkillRecordingDraft(
  id: string,
  body: SkillRecordingReview & { model: string; confirm_processing: true; preview_sha256: string },
): Promise<{
  draft: { name: string; description: string; content: string; files: []; evidence_summary: string[] }
  diagnostics: Array<{ code: string; message: string; severity: string }>
}> {
  return post(`/${encodeURIComponent(id)}/draft`, body)
}

export function skillRecordingScreenshotUrl(id: string, sequence: number): string {
  return `${apiBaseUrl()}/skill-recordings/${encodeURIComponent(id)}/screenshots/${sequence}`
}

export function skillRecordingVideoUrl(id: string): string {
  return `${apiBaseUrl()}/skill-recordings/${encodeURIComponent(id)}/video`
}
