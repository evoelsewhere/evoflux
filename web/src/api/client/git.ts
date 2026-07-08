/**
 * EvoFlux API client — git group: /team/workspace/git/* source control.
 */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  GitChangesResponse,
  GitCommitResponse,
  GitBranch,
  GitMergeResponse,
  GitJobOut,
  GitLogResponse,
  GitLogFile,
  GitStash,
  GitConflictsResponse,
} from '../types'

function wsParam(workspace: string): URLSearchParams {
  return new URLSearchParams({ workspace })
}

export async function getGitChanges(workspace: string): Promise<GitChangesResponse> {
  const params = wsParam(workspace)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/changes?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getGitChanges')
  return res.json()
}

export async function gitStage(workspace: string, paths?: string[]): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/stage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, paths }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitStage')
}

export async function gitUnstage(workspace: string, paths?: string[]): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/unstage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, paths }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitUnstage')
}

export async function gitDiscard(workspace: string, paths?: string[]): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/discard`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, paths }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitDiscard')
}

export async function gitCommit(workspace: string, message: string, amend?: boolean): Promise<GitCommitResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/commit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, message, amend }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitCommit')
  return res.json()
}

export async function gitBranches(workspace: string): Promise<GitBranch[]> {
  const params = wsParam(workspace)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/branches?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'gitBranches')
  return res.json()
}

export async function gitCheckout(workspace: string, name: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/branches/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitCheckout')
}

export async function gitCreateBranch(workspace: string, name: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/branches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitCreateBranch')
}

export async function gitDeleteBranch(workspace: string, name: string, force?: boolean): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/branches`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name, force }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitDeleteBranch')
}

export async function gitMerge(workspace: string, branch: string): Promise<GitMergeResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, branch }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitMerge')
  return res.json()
}

export async function gitFetch(workspace: string, remote?: string): Promise<GitJobOut> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/fetch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, remote }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitFetch')
  return res.json()
}

export async function gitPull(workspace: string, rebase?: boolean): Promise<GitJobOut> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/pull`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, rebase }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitPull')
  return res.json()
}

export async function gitPush(workspace: string, forceWithLease?: boolean): Promise<GitJobOut> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/push`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, force_with_lease: forceWithLease }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitPush')
  return res.json()
}

export async function gitJobs(workspace: string): Promise<GitJobOut | null> {
  const params = wsParam(workspace)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/jobs?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'gitJobs')
  return res.json()
}

export async function gitLog(
  workspace: string,
  options?: { skip?: number; limit?: number; branch?: string },
): Promise<GitLogResponse> {
  const params = wsParam(workspace)
  if (options?.skip != null) params.set('skip', String(options.skip))
  if (options?.limit != null) params.set('limit', String(options.limit))
  if (options?.branch) params.set('branch', options.branch)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/log?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'gitLog')
  return res.json()
}

export async function gitLogFiles(workspace: string, sha: string): Promise<GitLogFile[]> {
  const params = wsParam(workspace)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/log/${encodeURIComponent(sha)}/files?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'gitLogFiles')
  return res.json()
}

export async function gitStashes(workspace: string): Promise<GitStash[]> {
  const params = wsParam(workspace)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/stash?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'gitStashes')
  return res.json()
}

export async function gitStashCreate(workspace: string, message?: string, includeUntracked?: boolean): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/stash`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, message, include_untracked: includeUntracked }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitStashCreate')
}

export async function gitStashApply(workspace: string, index?: number): Promise<GitMergeResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/stash/apply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, index }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitStashApply')
  return res.json()
}

export async function gitStashPop(workspace: string, index?: number): Promise<GitMergeResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/stash/pop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, index }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitStashPop')
  return res.json()
}

export async function gitStashDrop(workspace: string, index?: number): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/stash`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, index }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitStashDrop')
}

export async function gitRebase(workspace: string, onto: string): Promise<GitMergeResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/rebase`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, onto }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitRebase')
  return res.json()
}

export async function gitCherryPick(workspace: string, shas: string[]): Promise<GitMergeResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/cherry-pick`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, shas }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitCherryPick')
  return res.json()
}

export async function gitConflicts(workspace: string): Promise<GitConflictsResponse> {
  const params = wsParam(workspace)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/conflicts?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'gitConflicts')
  return res.json()
}

export async function gitContinue(workspace: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/continue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitContinue')
}

export async function gitAbort(workspace: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/abort`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitAbort')
}

export async function getGitDiffView(workspace: string, path: string): Promise<{ diff: string }> {
  const params = new URLSearchParams({ workspace, path })
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/diff-view?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getGitDiffView')
  return res.json()
}
