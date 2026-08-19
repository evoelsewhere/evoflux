import type { CodingProblem, ProblemsResponse } from '../types'
import { apiUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'

function problemsUrl(workspace: string, suffix = '', includeResolved = false): string {
  const params = new URLSearchParams({
    workspace,
    include_resolved: String(includeResolved),
  })
  return apiUrl(`/team/workspace/problems${suffix}?${params}`)
}

export async function getProblems(
  workspace: string,
  includeResolved = false,
): Promise<ProblemsResponse> {
  const res = await fetch(problemsUrl(workspace, '', includeResolved), {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getProblems')
  return res.json()
}

async function updateProblem(
  workspace: string,
  problemId: string,
  action: 'dismiss' | 'suppress',
): Promise<CodingProblem> {
  const suffix = `/${encodeURIComponent(problemId)}/${action}`
  const res = await fetch(problemsUrl(workspace, suffix), { method: 'POST' })
  if (!res.ok) await parseDetailOrThrow(res, `${action}Problem`)
  return res.json()
}

export function dismissProblem(workspace: string, problemId: string): Promise<CodingProblem> {
  return updateProblem(workspace, problemId, 'dismiss')
}

export function suppressProblem(workspace: string, problemId: string): Promise<CodingProblem> {
  return updateProblem(workspace, problemId, 'suppress')
}
