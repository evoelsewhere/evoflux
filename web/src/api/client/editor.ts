import type {
  EditorActionRequest,
  EditorActionResponse,
  EditorContextRequest,
  EditorContextResponse,
} from '../types'
import { apiUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'

function editorUrl(workspace: string, action: 'context' | 'action'): string {
  const params = new URLSearchParams({ workspace })
  return apiUrl(`/team/workspace/editor/${action}?${params}`)
}

export async function previewEditorContext(
  workspace: string,
  request: EditorContextRequest,
  signal?: AbortSignal,
): Promise<EditorContextResponse> {
  const res = await fetch(editorUrl(workspace, 'context'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (!res.ok) await parseDetailOrThrow(res, 'previewEditorContext')
  return res.json()
}

export async function runEditorAction(
  workspace: string,
  request: EditorActionRequest,
  signal?: AbortSignal,
): Promise<EditorActionResponse> {
  const res = await fetch(editorUrl(workspace, 'action'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (!res.ok) await parseDetailOrThrow(res, 'runEditorAction')
  return res.json()
}
