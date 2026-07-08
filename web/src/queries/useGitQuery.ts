import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getGitChanges,
  gitStage,
  gitUnstage,
  gitDiscard,
  gitCommit,
  gitBranches,
  gitCheckout,
  gitCreateBranch,
  gitDeleteBranch,
  gitMerge,
  gitFetch,
  gitPull,
  gitPush,
  gitJobs,
  gitLog,
  gitLogFiles,
  gitStashes,
  gitStashCreate,
  gitStashApply,
  gitStashPop,
  gitStashDrop,
  gitRebase,
  gitCherryPick,
  gitConflicts,
  gitContinue,
  gitAbort,
  getGitDiffView,
} from '@/api/client'
import { queryKeys } from './keys'

// ── Helpers ──────────────────────────────────────────────────────────────────

function useInvalidateGitState(ws: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: queryKeys.git.changes(ws) })
    qc.invalidateQueries({ queryKey: queryKeys.coding.diff(ws) })
    qc.invalidateQueries({ queryKey: queryKeys.coding.status(ws) })
  }
}

// ── Read hooks ──────────────────────────────────────────────────────────────

export function useGitChangesQuery(workspace: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.git.changes(workspace),
    queryFn: () => getGitChanges(workspace),
    enabled,
    staleTime: 5_000,
  })
}

export function useGitBranchesQuery(workspace: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.git.branches(workspace),
    queryFn: () => gitBranches(workspace),
    enabled,
    staleTime: 10_000,
  })
}

export function useGitLogQuery(
  workspace: string,
  page: number,
  options?: { branch?: string },
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.git.log(workspace, page),
    queryFn: () => gitLog(workspace, { skip: page * 50, limit: 50, branch: options?.branch }),
    enabled,
    staleTime: 10_000,
  })
}

export function useGitLogFilesQuery(workspace: string, sha: string | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.git.logFiles(workspace, sha ?? ''),
    queryFn: () => gitLogFiles(workspace, sha!),
    enabled: enabled && !!sha,
    staleTime: 30_000,
  })
}

export function useGitStashesQuery(workspace: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.git.stashes(workspace),
    queryFn: () => gitStashes(workspace),
    enabled,
    staleTime: 10_000,
  })
}

export function useGitJobsQuery(workspace: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.git.jobs(workspace),
    queryFn: () => gitJobs(workspace),
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data
      if (data && data.status === 'running') return 1_000
      return false
    },
    staleTime: 0,
  })
}

export function useGitConflictsQuery(workspace: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.git.conflicts(workspace),
    queryFn: () => gitConflicts(workspace),
    enabled,
    staleTime: 5_000,
  })
}

export function useGitDiffViewQuery(workspace: string, path: string | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.git.diffView(workspace, path ?? ''),
    queryFn: () => getGitDiffView(workspace, path!),
    enabled: enabled && !!path,
    staleTime: 10_000,
  })
}

// ── Mutations ───────────────────────────────────────────────────────────────

export function useGitStageMutation(workspace: string) {
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (paths?: string[]) => gitStage(workspace, paths),
    onSuccess: () => {
      invalidateGitState()
    },
  })
}

export function useGitUnstageMutation(workspace: string) {
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (paths?: string[]) => gitUnstage(workspace, paths),
    onSuccess: () => {
      invalidateGitState()
    },
  })
}

export function useGitDiscardMutation(workspace: string) {
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (paths?: string[]) => gitDiscard(workspace, paths),
    onSuccess: () => {
      invalidateGitState()
    },
  })
}

export function useGitCommitMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: ({ message, amend }: { message: string; amend?: boolean }) =>
      gitCommit(workspace, message, amend),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.log(workspace, 0) })
    },
  })
}

export function useGitCheckoutMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (name: string) => gitCheckout(workspace, name),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.branches(workspace) })
    },
  })
}

export function useGitCreateBranchMutation(workspace: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => gitCreateBranch(workspace, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.git.branches(workspace) })
    },
  })
}

export function useGitDeleteBranchMutation(workspace: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, force }: { name: string; force?: boolean }) =>
      gitDeleteBranch(workspace, name, force),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.git.branches(workspace) })
    },
  })
}

export function useGitMergeMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (branch: string) => gitMerge(workspace, branch),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.branches(workspace) })
      qc.invalidateQueries({ queryKey: queryKeys.git.conflicts(workspace) })
    },
  })
}

export function useGitFetchMutation(workspace: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (remote?: string) => gitFetch(workspace, remote),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.git.changes(workspace) })
      qc.invalidateQueries({ queryKey: queryKeys.git.branches(workspace) })
    },
  })
}

export function useGitPullMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (rebase?: boolean) => gitPull(workspace, rebase),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.branches(workspace) })
      qc.invalidateQueries({ queryKey: queryKeys.git.log(workspace, 0) })
    },
  })
}

export function useGitPushMutation(workspace: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (forceWithLease?: boolean) => gitPush(workspace, forceWithLease),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.git.changes(workspace) })
      qc.invalidateQueries({ queryKey: queryKeys.git.branches(workspace) })
    },
  })
}

export function useGitStashCreateMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: ({ message, includeUntracked }: { message?: string; includeUntracked?: boolean } = {}) =>
      gitStashCreate(workspace, message, includeUntracked),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.stashes(workspace) })
    },
  })
}

export function useGitStashApplyMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (index?: number) => gitStashApply(workspace, index),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.conflicts(workspace) })
    },
  })
}

export function useGitStashPopMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (index?: number) => gitStashPop(workspace, index),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.stashes(workspace) })
      qc.invalidateQueries({ queryKey: queryKeys.git.conflicts(workspace) })
    },
  })
}

export function useGitStashDropMutation(workspace: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (index?: number) => gitStashDrop(workspace, index),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.git.stashes(workspace) })
      qc.invalidateQueries({ queryKey: queryKeys.git.changes(workspace) })
    },
  })
}

export function useGitRebaseMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (onto: string) => gitRebase(workspace, onto),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.branches(workspace) })
      qc.invalidateQueries({ queryKey: queryKeys.git.conflicts(workspace) })
    },
  })
}

export function useGitCherryPickMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: (shas: string[]) => gitCherryPick(workspace, shas),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.log(workspace, 0) })
      qc.invalidateQueries({ queryKey: queryKeys.git.conflicts(workspace) })
    },
  })
}

export function useGitContinueMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: () => gitContinue(workspace),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.conflicts(workspace) })
    },
  })
}

export function useGitAbortMutation(workspace: string) {
  const qc = useQueryClient()
  const invalidateGitState = useInvalidateGitState(workspace)
  return useMutation({
    mutationFn: () => gitAbort(workspace),
    onSuccess: () => {
      invalidateGitState()
      qc.invalidateQueries({ queryKey: queryKeys.git.conflicts(workspace) })
    },
  })
}
