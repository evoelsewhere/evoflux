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
  GitRemote,
  GitRepository,
  GitTag,
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

export async function getGitRepository(workspace: string): Promise<GitRepository> {
  const params = wsParam(workspace)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/repository?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getGitRepository')
  return res.json()
}

export async function gitInit(workspace: string, defaultBranch = 'main'): Promise<GitRepository> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/repository/init`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, default_branch: defaultBranch }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitInit')
  return res.json()
}

export async function gitSetIdentity(
  workspace: string,
  name: string,
  email: string,
): Promise<GitRepository> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/repository/identity`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name, email }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitSetIdentity')
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

export async function gitCheckout(workspace: string, name: string, track = false): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/branches/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name, track }),
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

export async function gitFetch(
  workspace: string,
  options?: { remote?: string; prune?: boolean },
): Promise<GitJobOut> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/fetch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, remote: options?.remote, prune: options?.prune }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitFetch')
  return res.json()
}

export async function gitPull(
  workspace: string,
  options?: { remote?: string; branch?: string; rebase?: boolean },
): Promise<GitJobOut> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/pull`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, ...options }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitPull')
  return res.json()
}

export async function gitPush(
  workspace: string,
  options?: {
    remote?: string
    branch?: string
    setUpstream?: boolean
    forceWithLease?: boolean
  },
): Promise<GitJobOut> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/push`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workspace,
      remote: options?.remote,
      branch: options?.branch,
      set_upstream: options?.setUpstream,
      force_with_lease: options?.forceWithLease,
    }),
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

export async function gitRemotes(workspace: string): Promise<GitRemote[]> {
  const params = wsParam(workspace)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/remotes?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'gitRemotes')
  return res.json()
}

export async function gitCreateRemote(workspace: string, name: string, url: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/remotes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name, url }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitCreateRemote')
}

export async function gitUpdateRemote(workspace: string, name: string, url: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/remotes`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name, url }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitUpdateRemote')
}

export async function gitDeleteRemote(workspace: string, name: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/remotes`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitDeleteRemote')
}

export async function gitTags(workspace: string): Promise<GitTag[]> {
  const params = wsParam(workspace)
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/tags?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'gitTags')
  return res.json()
}

export async function gitCreateTag(
  workspace: string,
  name: string,
  options?: { target?: string; message?: string },
): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name, ...options }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitCreateTag')
}

export async function gitDeleteTag(workspace: string, name: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/tags`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, name }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitDeleteTag')
}

export async function gitPushTags(
  workspace: string,
  options?: { remote?: string; tag?: string },
): Promise<GitJobOut> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/tags/push`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, ...options }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitPushTags')
  return res.json()
}

export async function gitLog(
  workspace: string,
  options?: { skip?: number; limit?: number; branch?: string; allBranches?: boolean },
): Promise<GitLogResponse> {
  const params = wsParam(workspace)
  if (options?.skip != null) params.set('skip', String(options.skip))
  if (options?.limit != null) params.set('limit', String(options.limit))
  if (options?.branch) params.set('branch', options.branch)
  if (options?.allBranches) params.set('all_branches', 'true')
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

export async function gitRevert(workspace: string, sha: string): Promise<GitMergeResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git/revert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, sha }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'gitRevert')
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
