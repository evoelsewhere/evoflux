import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  ExternalLink,
  FileDiff,
  GitCommitHorizontal,
  GitMerge,
  GitPullRequest,
  KeyRound,
  Loader2,
  MessageSquare,
  Minus,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  Users,
  XCircle,
  type LucideIcon,
} from 'lucide-react'

import type {
  CodeReviewItem,
  CodeReviewComment,
  CodeReviewContext,
  GitServerConnection,
  GitServerConnectionInput,
  GitServerConnectionScope,
  GitServerProvider,
  RepositoryCodeReviews,
} from '@/api/types'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Switch } from '@/components/ui/switch'
import { openExternalUrl } from '@/lib/open-external'
import {
  codeReviewSessionKey,
  parseCodeReviewSessionTags,
  type CodeReviewSessionContext,
} from '@/lib/code-review-session'
import {
  useCodeReviewsQuery,
  useCodeReviewActionMutation,
  useCodeReviewQuery,
  useDeleteGitServerConnectionMutation,
  useGitServerConnectionsQuery,
  useSaveGitServerConnectionMutation,
  useTestGitServerConnectionMutation,
} from '@/queries'
import { useTeamSessionsQuery } from '@/queries/useSessionsQuery'
import { formatRelativeDate } from '@/utils/format'
import { cn } from '@/lib/utils'
import type { PullRequestsScope } from '@/stores/useUIStore'

type ReviewFilter = 'all' | 'ready' | 'draft'

const PROVIDERS: Array<{
  value: GitServerProvider
  label: string
  reviewName: string
}> = [
  { value: 'github', label: 'GitHub / Enterprise', reviewName: 'Pull request' },
  { value: 'gitlab', label: 'GitLab / Self-Managed', reviewName: 'Merge request' },
  { value: 'bitbucket_cloud', label: 'Bitbucket Cloud', reviewName: 'Pull request' },
  { value: 'bitbucket_server', label: 'Bitbucket Data Center', reviewName: 'Pull request' },
  { value: 'gitea', label: 'Gitea / Forgejo', reviewName: 'Pull request' },
  { value: 'azure_devops', label: 'Azure DevOps', reviewName: 'Pull request' },
]

const FILTERS: ReadonlyArray<{ value: ReviewFilter; label: string }> = [
  { value: 'all', label: 'Open' },
  { value: 'ready', label: 'Ready' },
  { value: 'draft', label: 'Drafts' },
]

const SCOPES: ReadonlyArray<{
  value: GitServerConnectionScope
  label: string
}> = [
  { value: 'server', label: 'Shared server' },
  { value: 'repository', label: 'This repository' },
]

function providerLabel(provider: GitServerProvider | null): string {
  return PROVIDERS.find((item) => item.value === provider)?.label ?? 'Git server'
}

function providerReviewName(provider: GitServerProvider | null): string {
  return PROVIDERS.find((item) => item.value === provider)?.reviewName ?? 'Review'
}

type StatusTone = 'success' | 'warning' | 'danger' | 'neutral'

const STATUS_TONE_CLASSES: Record<StatusTone, string> = {
  success: 'bg-(--color-success-subtle) text-(--color-success)',
  warning: 'bg-(--color-warning-subtle) text-(--color-warning)',
  danger: 'bg-(--color-error-subtle) text-(--color-error)',
  neutral: 'bg-(--bg-key) text-(--color-text-muted)',
}

function humanizeStatus(value: string): string {
  return value.replaceAll('_', ' ').replaceAll('-', ' ')
}

function statusTone(value: string): StatusTone {
  const normalized = value.toLowerCase()
  if (
    ['approved', 'clean', 'completed', 'mergeable', 'passed', 'success', 'succeeded'].some(
      (candidate) => normalized.includes(candidate),
    )
  ) return 'success'
  if (
    ['blocked', 'cannot', 'changes requested', 'conflict', 'error', 'fail'].some(
      (candidate) => normalized.includes(candidate),
    )
  ) return 'danger'
  if (
    ['pending', 'queued', 'running', 'checking', 'draft', 'unknown', 'unavailable'].some(
      (candidate) => normalized.includes(candidate),
    )
  ) return 'warning'
  return 'neutral'
}

function StatusPill({ label, value }: { label?: string; value: string }) {
  const tone = statusTone(value)
  return (
    <span className={cn(
      'inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium capitalize',
      STATUS_TONE_CLASSES[tone],
    )}>
      {tone === 'success' && <CheckCircle2 size={10} aria-hidden="true" />}
      {tone === 'danger' && <XCircle size={10} aria-hidden="true" />}
      {tone === 'warning' && <AlertCircle size={10} aria-hidden="true" />}
      {label && <span className="text-current/70">{label}</span>}
      {humanizeStatus(value)}
    </span>
  )
}

function mergeabilityStatus(
  mergeability: CodeReviewContext['mergeability'],
): { label: string; tone: StatusTone } {
  if (mergeability.merged) return { label: 'Merged', tone: 'success' }
  if (mergeability.conflicts) return { label: 'Conflicts', tone: 'danger' }
  const value = String(mergeability.mergeable ?? '').toLowerCase()
  if (['true', 'clean', 'mergeable', 'can_be_merged'].includes(value)) {
    return { label: 'Mergeable', tone: 'success' }
  }
  if (['false', 'dirty', 'cannot_be_merged', 'conflicts'].includes(value)) {
    return { label: 'Blocked', tone: 'danger' }
  }
  return { label: 'Checking', tone: 'warning' }
}

function SummaryMetric({
  Icon,
  value,
  label,
  tone,
}: {
  Icon: LucideIcon
  value: number
  label: string
  tone?: 'positive' | 'negative'
}) {
  return (
    <div className="flex min-w-0 items-center gap-2 px-3 py-2.5">
      <Icon
        size={14}
        className={cn(
          'shrink-0 text-(--color-text-subtle)',
          tone === 'positive' && 'text-(--color-success)',
          tone === 'negative' && 'text-(--color-error)',
        )}
        aria-hidden="true"
      />
      <span className="min-w-0">
        <span className="block text-sm font-semibold tabular-nums text-(--color-text)">
          {value.toLocaleString()}
        </span>
        <span className="block truncate text-[10px] text-(--color-text-muted)">
          {label}
        </span>
      </span>
    </div>
  )
}

function remoteHost(remoteUrl: string | null): string {
  if (!remoteUrl) return 'this host'
  try {
    const normalized = remoteUrl.includes('://')
      ? remoteUrl
      : remoteUrl.replace(/^(?:[^@]+@)?([^:]+):/, 'https://$1/')
    return new URL(normalized).hostname || 'this host'
  } catch {
    return 'this host'
  }
}

function suggestedServerDomain(
  target: RepositoryCodeReviews,
  provider: GitServerProvider,
): string {
  const host = remoteHost(target.remote_url)
  if (host === 'this host') return ''
  if (provider === 'bitbucket_cloud') return 'https://bitbucket.org'
  const organization = target.repository?.split('/')[0] ?? ''
  if (provider === 'azure_devops') {
    return `https://dev.azure.com/${organization}`
  }
  return `https://${host}`
}

function normalizeServerDomain(
  provider: GitServerProvider,
  value: string,
): string {
  const trimmed = value.trim().replace(/\/+$/, '')
  if (!trimmed) return ''
  try {
    const url = new URL(
      trimmed.includes('://') ? trimmed : `https://${trimmed}`,
    )
    if (provider === 'github' && url.hostname === 'api.github.com') {
      return 'https://github.com'
    }
    if (
      provider === 'bitbucket_cloud' &&
      url.hostname === 'api.bitbucket.org'
    ) {
      return 'https://bitbucket.org'
    }
    if (
      provider === 'azure_devops' &&
      url.hostname.endsWith('.visualstudio.com')
    ) {
      return `https://dev.azure.com/${url.hostname.split('.')[0]}`
    }
    const suffixes: Partial<Record<GitServerProvider, string>> = {
      github: '/api/v3',
      gitlab: '/api/v4',
      bitbucket_cloud: '/2.0',
      bitbucket_server: '/rest/api/1.0',
      gitea: '/api/v1',
    }
    const suffix = suffixes[provider]
    let path = url.pathname.replace(/\/+$/, '')
    if (suffix && path.toLowerCase().endsWith(suffix)) {
      path = path.slice(0, -suffix.length).replace(/\/+$/, '')
    }
    return `${url.protocol}//${url.host}${path}`
  } catch {
    return ''
  }
}

function inferredApiBase(
  provider: GitServerProvider,
  domain: string,
  repository: string | null,
): string {
  const root = normalizeServerDomain(provider, domain)
  if (!root) return ''
  const host = new URL(root).hostname
  if (provider === 'github') {
    return host === 'github.com' ? 'https://api.github.com' : `${root}/api/v3`
  }
  if (provider === 'gitlab') return `${root}/api/v4`
  if (provider === 'bitbucket_cloud') return 'https://api.bitbucket.org/2.0'
  if (provider === 'bitbucket_server') return `${root}/rest/api/1.0`
  if (provider === 'gitea') return `${root}/api/v1`
  const organization =
    new URL(root).pathname.split('/').filter(Boolean)[0] ??
    repository?.split('/')[0] ??
    ''
  return organization ? `https://dev.azure.com/${organization}` : ''
}

function tokenCreationUrl(
  provider: GitServerProvider,
  domain: string,
  repository: string | null,
): string {
  const root = normalizeServerDomain(provider, domain)
  if (!root) return ''
  if (provider === 'github') return `${root}/settings/tokens/new`
  if (provider === 'gitlab') {
    return `${root}/-/user_settings/personal_access_tokens`
  }
  if (provider === 'bitbucket_cloud') {
    return 'https://id.atlassian.com/manage-profile/security/api-tokens'
  }
  if (provider === 'bitbucket_server') {
    return `${root}/plugins/servlet/access-tokens/manage`
  }
  if (provider === 'gitea') return `${root}/user/settings/applications`
  const apiBase = inferredApiBase(provider, root, repository)
  return apiBase ? `${apiBase}/_usersSettings/tokens` : ''
}

function ReviewRow({
  repository,
  item,
  provider,
  linked,
  focused,
  opening,
  onOpenInChat,
  onInspect,
}: {
  repository: RepositoryCodeReviews
  item: CodeReviewItem
  provider: GitServerProvider | null
  linked: boolean
  focused: boolean
  opening: boolean
  onOpenInChat: (
    repository: RepositoryCodeReviews,
    item: CodeReviewItem,
  ) => Promise<void>
  onInspect: (repository: RepositoryCodeReviews, item: CodeReviewItem) => void
}) {
  const Icon = provider === 'gitlab' ? GitMerge : GitPullRequest
  const reviewKey = codeReviewSessionKey(repository.workspace_id, item.number)
  return (
    <div
      data-review-key={reviewKey}
      className={cn(
        'group flex w-full gap-2.5 border-t border-(--color-border)/70 px-3 py-2.5 text-left transition-colors first:border-t-0 hover:bg-(--bg-key)/60',
        focused && 'bg-(--accent-blue-soft) ring-1 ring-inset ring-(--accent-blue)/35',
      )}
    >
      <Icon
        size={15}
        className={
          item.draft
            ? 'mt-0.5 shrink-0 text-(--color-text-subtle)'
            : 'mt-0.5 shrink-0 text-(--color-success)'
        }
      />
      <div className="min-w-0 flex-1">
        <span className="flex items-start gap-2">
          <button
            type="button"
            onClick={() => onInspect(repository, item)}
            className="min-w-0 flex-1 truncate text-left text-sm font-medium leading-5 text-(--color-text) hover:text-(--color-accent)"
            title={item.title}
          >
            {item.title}
          </button>
          {item.web_url && (
            <button
              type="button"
              onClick={() => void openExternalUrl(item.web_url)}
              className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-(--color-text-subtle) opacity-60 hover:bg-(--bg-key) hover:text-(--color-text) group-hover:opacity-100"
              aria-label={`Open review #${item.number} in browser`}
              title="Open in browser"
            >
              <ExternalLink size={12} />
            </button>
          )}
          <button
            type="button"
            onClick={() => void onOpenInChat(repository, item)}
            disabled={opening}
            className="inline-flex h-6 shrink-0 items-center gap-1 rounded-md border border-(--color-border) bg-(--bg-card) px-2 text-[11px] font-medium text-(--color-text-muted) shadow-sm transition-colors hover:border-(--color-accent)/45 hover:text-(--color-accent) disabled:opacity-60"
            title={linked ? 'Continue review chat' : 'Review in chat'}
          >
            {opening ? (
              <Loader2 size={11} className="animate-spin" />
            ) : (
              <MessageSquare size={11} />
            )}
            {linked ? 'Continue' : 'Review'}
          </button>
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-(--color-text-muted)">
          <span>#{item.number}</span>
          <StatusPill value={item.draft ? 'draft' : item.state || 'open'} />
          {item.author && <span>by {item.author}</span>}
          {item.updated_at && <span>{formatRelativeDate(item.updated_at)}</span>}
          {item.comment_count !== null && (
            <span className="inline-flex items-center gap-1">
              <MessageSquare size={10} />
              {item.comment_count}
            </span>
          )}
        </span>
        <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-(--color-text-subtle)">
          {item.source_branch && (
            <span className="inline-flex min-w-0 items-center gap-1 font-mono">
              <span className="max-w-36 truncate">{item.source_branch}</span>
              <ArrowRight size={10} className="shrink-0" />
              <span className="max-w-28 truncate">{item.target_branch}</span>
            </span>
          )}
          {item.review_status && (
            <StatusPill label="Review" value={item.review_status} />
          )}
          {item.pipeline_status && (
            <StatusPill label="Checks" value={item.pipeline_status} />
          )}
          {item.labels.slice(0, 2).map((label) => (
            <span
              key={label}
              className="rounded-full border border-(--color-border) px-1.5 py-0.5 text-[10px] text-(--color-text-muted)"
            >
              {label}
            </span>
          ))}
        </span>
      </div>
    </div>
  )
}

function ReviewCommentCard({
  comment,
  pending,
  onReply,
  onToggleResolved,
}: {
  comment: CodeReviewComment
  pending: boolean
  onReply: (comment: CodeReviewComment, body: string) => Promise<void>
  onToggleResolved: (comment: CodeReviewComment) => Promise<void>
}) {
  const [reply, setReply] = useState('')
  return (
    <div className="rounded-lg border border-(--color-border) bg-(--bg-card) p-3">
      <div className="flex items-center gap-2 text-[11px] text-(--color-text-muted)">
        <span className="font-medium text-(--color-text)">
          {comment.author ?? 'Unknown author'}
        </span>
        {comment.kind === 'inline' && comment.path && (
          <span className="min-w-0 truncate font-mono">
            {comment.path}{comment.line ? `:${comment.line}` : ''}
          </span>
        )}
        {comment.resolved !== null && (
          <span
            className={cn(
              'ml-auto rounded-full px-1.5 py-0.5',
              comment.resolved
                ? 'bg-(--color-success-subtle) text-(--color-success)'
                : 'bg-(--color-warning-subtle) text-(--color-warning)',
            )}
          >
            {comment.resolved ? 'Resolved' : 'Unresolved'}
          </span>
        )}
      </div>
      <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-(--color-text-2)">
        {comment.body}
      </p>
      <div className="mt-2 flex items-center gap-2">
        {comment.can_resolve && comment.resolved !== null && (
          <Button
            size="sm"
            variant="outline"
            disabled={pending}
            onClick={() => void onToggleResolved(comment)}
          >
            {comment.resolved ? 'Reopen' : 'Resolve'}
          </Button>
        )}
        {comment.can_reply && (
          <>
            <Input
              value={reply}
              onChange={(event) => setReply(event.target.value)}
              placeholder="Reply to thread…"
              className="h-7 min-w-0 flex-1 text-xs"
            />
            <Button
              size="sm"
              disabled={pending || !reply.trim()}
              onClick={() => {
                const value = reply.trim()
                if (!value) return
                void onReply(comment, value).then(() => setReply(''))
              }}
            >
              Reply
            </Button>
          </>
        )}
      </div>
    </div>
  )
}

function ReviewDetails({
  repository,
  item,
  onBack,
  onOpenInChat,
}: {
  repository: RepositoryCodeReviews
  item: CodeReviewItem
  onBack: () => void
  onOpenInChat: (
    repository: RepositoryCodeReviews,
    item: CodeReviewItem,
  ) => Promise<void>
}) {
  const detail = useCodeReviewQuery(repository.workspace_id, item.number)
  const action = useCodeReviewActionMutation(
    repository.workspace_id,
    item.number,
  )
  const [comment, setComment] = useState('')

  const mutate = async (input: Parameters<typeof action.mutateAsync>[0]) => {
    await action.mutateAsync(input)
    await detail.refetch()
  }
  const capabilities = detail.data?.capabilities ?? {}
  const summary = detail.data?.summary
  const mergeability = detail.data
    ? mergeabilityStatus(detail.data.mergeability)
    : null
  const approvedCount = detail.data?.approvals.filter(
    (approval) => approval.state === 'approved',
  ).length ?? 0
  const hasMetrics = Boolean(summary && [
    summary.commit_count,
    summary.changed_files,
    summary.additions,
    summary.deletions,
  ].some((value) => value !== null))
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-(--color-border) p-3">
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={onBack}
            className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key)"
            aria-label="Back to pull requests"
          >
            <ChevronLeft size={15} />
          </button>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-(--color-text)">
              {item.title}
            </h3>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-(--color-text-muted)">
              <span>{repository.repository ?? repository.name} · #{item.number}</span>
              <StatusPill value={item.draft ? 'draft' : item.state || 'open'} />
              {(summary?.author ?? item.author) && (
                <span>by {summary?.author ?? item.author}</span>
              )}
              {(summary?.updated_at ?? item.updated_at) && (
                <span>{formatRelativeDate(summary?.updated_at ?? item.updated_at)}</span>
              )}
            </div>
          </div>
          {item.web_url && (
            <button
              type="button"
              onClick={() => void openExternalUrl(item.web_url)}
              className="flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
              aria-label={`Open review #${item.number} in browser`}
              title="Open in browser"
            >
              <ExternalLink size={13} />
            </button>
          )}
          <button
            type="button"
            onClick={() => void detail.refetch()}
            disabled={detail.isFetching}
            className="flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key)"
            aria-label="Refresh review context"
          >
            <RefreshCw
              size={13}
              className={detail.isFetching ? 'animate-spin' : ''}
            />
          </button>
        </div>
        {(summary?.source_branch ?? item.source_branch) && (
          <div className="mt-2 flex min-w-0 items-center gap-1.5 rounded-md bg-(--bg-key)/70 px-2 py-1.5 font-mono text-[10px] text-(--color-text-muted)">
            <span className="truncate">{summary?.source_branch ?? item.source_branch}</span>
            <ArrowRight size={10} className="shrink-0" aria-hidden="true" />
            <span className="truncate">{summary?.target_branch ?? item.target_branch}</span>
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {capabilities.submit_approve && (
            <Button
              size="sm"
              variant="outline"
              disabled={action.isPending}
              onClick={() => void mutate({ action: 'approve' })}
            >
              <CheckCircle2 size={13} />
              Approve
            </Button>
          )}
          {capabilities.submit_request_changes && (
            <Button
              size="sm"
              variant="outline"
              disabled={action.isPending}
              onClick={() =>
                void mutate({
                  action: 'request_changes',
                  body: comment.trim() || undefined,
                })
              }
            >
              <XCircle size={13} />
              Request changes
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => void onOpenInChat(repository, item)}
          >
            <MessageSquare size={13} />
            Review in chat
          </Button>
        </div>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {detail.isLoading && (
          <div className="flex items-center justify-center gap-2 py-12 text-xs text-(--color-text-muted)">
            <Loader2 size={14} className="animate-spin" />
            Loading review context…
          </div>
        )}
        {detail.error && (
          <p className="rounded-lg bg-(--color-error-subtle) p-3 text-xs text-(--color-error)">
            {detail.error instanceof Error
              ? detail.error.message
              : String(detail.error)}
          </p>
        )}
        {detail.data && (
          <>
            <section className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h4 className="text-xs font-semibold text-(--color-text)">
                  Overview
                </h4>
                {summary?.created_at && (
                  <span className="text-[10px] text-(--color-text-subtle)">
                    Opened {formatRelativeDate(summary.created_at)}
                  </span>
                )}
              </div>
              {summary?.description ? (
                <p className="whitespace-pre-wrap text-xs leading-5 text-(--color-text-2)">
                  {summary.description}
                </p>
              ) : (
                <p className="text-xs italic text-(--color-text-subtle)">
                  No description provided.
                </p>
              )}
              {hasMetrics && summary && (
                <div className="grid grid-cols-2 divide-x divide-y divide-(--color-border) overflow-hidden rounded-md border border-(--color-border) sm:grid-cols-4 sm:divide-y-0">
                  {summary.commit_count !== null && (
                    <SummaryMetric Icon={GitCommitHorizontal} value={summary.commit_count} label="commits" />
                  )}
                  {summary.changed_files !== null && (
                    <SummaryMetric Icon={FileDiff} value={summary.changed_files} label="files changed" />
                  )}
                  {summary.additions !== null && (
                    <SummaryMetric Icon={Plus} value={summary.additions} label="additions" tone="positive" />
                  )}
                  {summary.deletions !== null && (
                    <SummaryMetric Icon={Minus} value={summary.deletions} label="deletions" tone="negative" />
                  )}
                </div>
              )}
              {(summary?.reviewers.length || summary?.assignees.length) ? (
                <div className="space-y-1.5 text-[11px] text-(--color-text-muted)">
                  {summary.reviewers.length > 0 && (
                    <div className="flex items-start gap-2">
                      <Users size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                      <span className="w-16 shrink-0">Reviewers</span>
                      <span className="text-(--color-text-2)">{summary.reviewers.join(', ')}</span>
                    </div>
                  )}
                  {summary.assignees.length > 0 && (
                    <div className="flex items-start gap-2">
                      <Users size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                      <span className="w-16 shrink-0">Assignees</span>
                      <span className="text-(--color-text-2)">{summary.assignees.join(', ')}</span>
                    </div>
                  )}
                </div>
              ) : null}
            </section>
            <section className="border-t border-(--color-border) pt-4">
              <h4 className="text-xs font-semibold text-(--color-text)">
                Merge readiness
              </h4>
              <div className="mt-2 grid grid-cols-3 divide-x divide-(--color-border) border-y border-(--color-border)">
                <div className="px-3 py-2.5">
                  <span className="block text-sm font-semibold text-(--color-text)">{approvedCount}</span>
                  <span className="text-[10px] text-(--color-text-muted)">approvals</span>
                </div>
                <div className="px-3 py-2.5">
                  <StatusPill value={detail.data.checks.summary} />
                  <span className="mt-1 block text-[10px] text-(--color-text-muted)">
                    {detail.data.checks.items.length} checks
                  </span>
                </div>
                <div className="px-3 py-2.5">
                  {mergeability && (
                    <span className={cn(
                      'inline-flex rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                      STATUS_TONE_CLASSES[mergeability.tone],
                    )}>
                      {mergeability.label}
                    </span>
                  )}
                  <span className="mt-1 block text-[10px] text-(--color-text-muted)">merge status</span>
                </div>
              </div>
              {detail.data.checks.items.length > 0 && (
                <div className="mt-3 divide-y divide-(--color-border) border-y border-(--color-border)">
                  {detail.data.checks.items.map((check) => (
                    <div key={check.id || check.name} className="flex items-center gap-2 py-2 text-[11px]">
                      {statusTone(check.status) === 'success' ? (
                        <CheckCircle2 size={12} className="shrink-0 text-(--color-success)" aria-hidden="true" />
                      ) : statusTone(check.status) === 'danger' ? (
                        <XCircle size={12} className="shrink-0 text-(--color-error)" aria-hidden="true" />
                      ) : (
                        <AlertCircle size={12} className="shrink-0 text-(--color-warning)" aria-hidden="true" />
                      )}
                      <span className="min-w-0 flex-1 truncate text-(--color-text-2)">{check.name}</span>
                      <span className="capitalize text-(--color-text-muted)">{humanizeStatus(check.status)}</span>
                      {check.url && (
                        <button
                          type="button"
                          onClick={() => void openExternalUrl(check.url)}
                          className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
                          aria-label={`Open ${check.name}`}
                        >
                          <ExternalLink size={11} />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
            <section className="border-t border-(--color-border) pt-4">
              <h4 className="text-xs font-semibold text-(--color-text)">
                Discussion
              </h4>
              <div className="mt-2 flex gap-2">
                <Input
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Add a review comment…"
                  className="min-w-0 flex-1 text-xs"
                />
                <Button
                  size="sm"
                  disabled={action.isPending || !comment.trim()}
                  onClick={() => {
                    const value = comment.trim()
                    if (!value) return
                    void mutate({
                      action: 'comment',
                      body: value,
                      idempotency_key: crypto.randomUUID(),
                    }).then(() => setComment(''))
                  }}
                >
                  Comment
                </Button>
              </div>
              <div className="mt-3 space-y-2">
                {detail.data.comments.length === 0 && (
                  <p className="rounded-lg border border-dashed border-(--color-border) p-4 text-center text-xs text-(--color-text-muted)">
                    No discussion yet.
                  </p>
                )}
                {detail.data.comments.map((entry) => (
                  <ReviewCommentCard
                    key={entry.stable_id}
                    comment={entry}
                    pending={action.isPending}
                    onReply={(target, body) =>
                      mutate({
                        action: 'reply',
                        thread_id: target.thread_id,
                        body,
                      }).then(() => undefined)
                    }
                    onToggleResolved={(target) =>
                      mutate({
                        action: target.resolved
                          ? 'reopen_thread'
                          : 'resolve_thread',
                        thread_id: target.thread_id,
                      }).then(() => undefined)
                    }
                  />
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  )
}

interface ConnectionDialogProps {
  target: RepositoryCodeReviews
  connection: GitServerConnection | null
  onClose: () => void
}

function ConnectionDialog({
  target,
  connection,
  onClose,
}: ConnectionDialogProps) {
  const save = useSaveGitServerConnectionMutation()
  const test = useTestGitServerConnectionMutation()
  const [name, setName] = useState(
    connection?.name ?? `${target.name} connection`,
  )
  const [provider, setProvider] = useState<GitServerProvider>(
    connection?.provider ?? target.detected_provider ?? 'github',
  )
  const [domain, setDomain] = useState(
    connection?.domain ??
      target.suggested_domain ??
      suggestedServerDomain(
        target,
        connection?.provider ?? target.detected_provider ?? 'github',
      ),
  )
  const [scope, setScope] = useState<GitServerConnectionScope>(
    connection?.scope ?? 'server',
  )
  const [token, setToken] = useState('')
  const [username, setUsername] = useState(connection?.username ?? '')
  const [verifySsl, setVerifySsl] = useState(
    connection?.verify_ssl ?? true,
  )
  const [tested, setTested] = useState(false)
  const apiBasePreview = inferredApiBase(
    provider,
    domain,
    target.repository,
  )
  const createTokenUrl = tokenCreationUrl(
    provider,
    domain,
    target.repository,
  )
  const savedCredentialMatches =
    connection?.has_token === true &&
    connection.scope === scope &&
    connection.provider === provider &&
    normalizeServerDomain(provider, connection.domain) ===
      normalizeServerDomain(provider, domain)

  const canSubmit =
    Boolean(name.trim() && apiBasePreview) &&
    (Boolean(token.trim()) || savedCredentialMatches)

  const testValues = async () => {
    if (!token.trim()) return
    try {
      await test.mutateAsync({
        provider,
        domain: domain.trim(),
        token: token.trim(),
        username: username.trim() || null,
        verify_ssl: verifySsl,
      })
      setTested(true)
    } catch {
      setTested(false)
    }
  }

  const submit = async () => {
    if (!canSubmit) return
    const body: GitServerConnectionInput = {
      name: name.trim(),
      provider,
      domain: domain.trim(),
      scope,
      workspace_id: scope === 'repository' ? target.workspace_id : null,
      username: username.trim() || null,
      verify_ssl: verifySsl,
    }
    if (token.trim()) body.token = token.trim()
    const updateId =
      connection?.scope === scope ? connection.id : undefined
    await save.mutateAsync({ id: updateId, body })
    onClose()
  }

  const error = test.error ?? save.error

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {connection ? 'Edit Git server connection' : 'Connect Git server'}
          </DialogTitle>
          <DialogDescription>
            {target
              ? `API access for ${target.repository ?? target.name}. The key is stored separately from repository metadata.`
              : 'Configure API access for this Git server.'}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <label className="grid gap-1">
            <span className="text-xs font-medium text-(--color-text-muted)">
              Connection name
            </span>
            <Input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="grid gap-1">
            <span className="text-xs font-medium text-(--color-text-muted)">
              Provider
            </span>
            <NativeSelect
              className="w-full"
              value={provider}
              onChange={(event) => {
                const nextProvider = event.target.value as GitServerProvider
                setProvider(nextProvider)
                setDomain(suggestedServerDomain(target, nextProvider))
                setTested(false)
              }}
            >
              {PROVIDERS.map((item) => (
                <NativeSelectOption key={item.value} value={item.value}>
                  {item.label}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
          <label className="grid gap-1">
            <span className="text-xs font-medium text-(--color-text-muted)">
              Git server domain
            </span>
            <Input
              value={domain}
              onChange={(event) => {
                setDomain(event.target.value)
                setTested(false)
              }}
              placeholder="git.example.com"
              spellCheck={false}
            />
            <span className="truncate text-[11px] text-(--color-text-subtle)">
              {apiBasePreview
                ? `API endpoint: ${apiBasePreview}`
                : 'Enter the server domain or root URL. The API endpoint is detected automatically.'}
            </span>
          </label>
          <div className="grid gap-1">
            <span className="text-xs font-medium text-(--color-text-muted)">
              Credential scope
            </span>
            <SegmentedControl
              options={SCOPES}
              value={scope}
              onChange={setScope}
              layoutId="git-connection-scope"
              ariaLabel="Credential scope"
            />
            <p className="text-[11px] text-(--color-text-subtle)">
              {scope === 'server'
                ? `Reuse this key for every repository on ${remoteHost(target?.remote_url ?? null)}.`
                : 'Override any shared key for this repository only.'}
            </p>
          </div>
          {(provider === 'azure_devops' ||
            provider === 'bitbucket_cloud') && (
            <label className="grid gap-1">
              <span className="text-xs font-medium text-(--color-text-muted)">
                {provider === 'azure_devops'
                  ? 'Username (optional for PAT)'
                  : 'Atlassian email (only for Basic API tokens)'}
              </span>
              <Input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
              />
            </label>
          )}
          <div className="grid gap-1">
            <span className="flex items-center justify-between gap-3">
              <label
                htmlFor="git-server-access-token"
                className="text-xs font-medium text-(--color-text-muted)"
              >
                API key / access token
              </label>
              <Button
                type="button"
                variant="link"
                size="xs"
                disabled={!createTokenUrl}
                onClick={() => void openExternalUrl(createTokenUrl)}
              >
                Generate token
                <ExternalLink data-icon="inline-end" />
              </Button>
            </span>
            <Input
              id="git-server-access-token"
              type="password"
              value={token}
              onChange={(event) => {
                setToken(event.target.value)
                setTested(false)
              }}
              placeholder={
                savedCredentialMatches
                  ? 'Leave blank to keep the saved key'
                  : connection?.has_token
                    ? 'Paste a token for this provider and domain'
                    : 'Paste a repository access token'
              }
              autoComplete="off"
            />
            <span className="text-[11px] text-(--color-text-subtle)">
              Generate token opens the provider page in your browser. Paste the
              token here after creating it.
            </span>
          </div>
          <div className="flex items-center justify-between rounded-lg border border-(--color-border) px-3 py-2">
            <span>
              <span className="block text-xs font-medium text-(--color-text)">
                Verify TLS certificates
              </span>
              <span className="block text-[11px] text-(--color-text-subtle)">
                Keep enabled unless the self-hosted server uses a private CA.
              </span>
            </span>
            <Switch
              checked={verifySsl}
              onCheckedChange={setVerifySsl}
              aria-label="Verify TLS certificates"
            />
          </div>
          {tested && (
            <p className="flex items-center gap-1.5 text-xs text-(--color-success)">
              <Check size={13} />
              Connection verified
            </p>
          )}
          {error && (
            <p className="rounded-lg bg-(--color-error-subtle) px-3 py-2 text-xs text-(--color-error)">
              {error instanceof Error ? error.message : String(error)}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="outline"
            onClick={() => void testValues()}
            disabled={!token.trim() || test.isPending}
          >
            {test.isPending && <Loader2 className="animate-spin" />}
            Test
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={!canSubmit || save.isPending}
          >
            {save.isPending && <Loader2 className="animate-spin" />}
            Save connection
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ConnectionsDialog({
  open,
  onClose,
  connections,
}: {
  open: boolean
  onClose: () => void
  connections: GitServerConnection[]
}) {
  const remove = useDeleteGitServerConnectionMutation()
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Git server connections</DialogTitle>
          <DialogDescription>
            Shared keys apply by Git hostname. Repository-scoped keys take
            precedence.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-80 space-y-2 overflow-y-auto">
          {connections.length === 0 && (
            <p className="rounded-lg border border-dashed border-(--color-border) p-4 text-center text-xs text-(--color-text-muted)">
              No connections yet. Configure one from a repository below.
            </p>
          )}
          {connections.map((connection) => (
            <div
              key={connection.id}
              className="flex items-center gap-3 rounded-lg border border-(--color-border) px-3 py-2"
            >
              <KeyRound size={14} className="text-(--color-text-muted)" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {connection.name}
                </span>
                <span className="block truncate text-[11px] text-(--color-text-subtle)">
                  {providerLabel(connection.provider)} · {connection.scope} ·{' '}
                  {connection.host}
                </span>
              </span>
              <button
                type="button"
                onClick={() => remove.mutate(connection.id)}
                disabled={remove.isPending}
                className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--color-error-subtle) hover:text-(--color-error)"
                aria-label={`Delete ${connection.name}`}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
        <DialogFooter showCloseButton />
      </DialogContent>
    </Dialog>
  )
}

interface PullRequestsPanelProps {
  open: boolean
  scope: PullRequestsScope
  workspace: string | null
  projectId: string | null
  focus: CodeReviewSessionContext | null
  onOpenInChat: (
    repository: RepositoryCodeReviews,
    item: CodeReviewItem,
  ) => Promise<void>
}

export function PullRequestsPanel({
  open,
  scope,
  workspace,
  projectId,
  focus,
  onOpenInChat,
}: PullRequestsPanelProps) {
  const reviewScope =
    scope === 'session'
      ? projectId
        ? { projectId }
        : { workspace }
      : {}
  const reviews = useCodeReviewsQuery(open, reviewScope)
  const connections = useGitServerConnectionsQuery(open)
  const codingSessions = useTeamSessionsQuery('coding')
  const contentRef = useRef<HTMLDivElement>(null)
  const [filter, setFilter] = useState<ReviewFilter>('all')
  const [repositoryFilter, setRepositoryFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [openingReviewKey, setOpeningReviewKey] = useState<string | null>(null)
  const [configTarget, setConfigTarget] =
    useState<RepositoryCodeReviews | null>(null)
  const [manageOpen, setManageOpen] = useState(false)
  const [selectedReview, setSelectedReview] = useState<{
    repository: RepositoryCodeReviews
    item: CodeReviewItem
  } | null>(null)

  const visibleRepositories = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (reviews.data?.repositories ?? [])
      .filter(
        (repository) =>
          repositoryFilter === 'all'
          || repository.workspace_id === repositoryFilter,
      )
      .map((repository) => ({
        ...repository,
        items: repository.items.filter((item) => {
          if (filter === 'ready' && item.draft) return false
          if (filter === 'draft' && !item.draft) return false
          if (!needle) return true
          return (
            item.title.toLowerCase().includes(needle) ||
            item.author?.toLowerCase().includes(needle) ||
            item.source_branch.toLowerCase().includes(needle) ||
            repository.name.toLowerCase().includes(needle) ||
            item.labels.some((label) => label.toLowerCase().includes(needle))
          )
        }),
      }))
  }, [filter, repositoryFilter, reviews.data?.repositories, search])

  const linkedReviewKeys = useMemo(() => {
    const keys = new Set<string>()
    for (const page of codingSessions.data?.pages ?? []) {
      for (const session of page.data) {
        const context = parseCodeReviewSessionTags(session.tags)
        if (context) {
          keys.add(codeReviewSessionKey(context.workspaceId, context.number))
        }
      }
    }
    return keys
  }, [codingSessions.data])

  const focusedReviewKey = focus
    ? codeReviewSessionKey(focus.workspaceId, focus.number)
    : null

  useEffect(() => {
    setRepositoryFilter('all')
  }, [projectId, scope, workspace])

  useEffect(() => {
    if (!open || !focus) return
    setFilter('all')
    setRepositoryFilter(focus.workspaceId)
    setSearch('')
  }, [focus, open])

  useEffect(() => {
    const repositories = reviews.data?.repositories ?? []
    if (
      repositoryFilter !== 'all'
      && !repositories.some(
        (repository) => repository.workspace_id === repositoryFilter,
      )
    ) {
      setRepositoryFilter('all')
    }
  }, [repositoryFilter, reviews.data?.repositories])

  useEffect(() => {
    if (!open || !focusedReviewKey) return
    const frame = window.requestAnimationFrame(() => {
      const target = Array.from(
        contentRef.current?.querySelectorAll<HTMLElement>('[data-review-key]')
          ?? [],
      ).find((element) => element.dataset.reviewKey === focusedReviewKey)
      target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [focusedReviewKey, open, visibleRepositories])

  const openReviewInChat = async (
    repository: RepositoryCodeReviews,
    item: CodeReviewItem,
  ) => {
    const key = codeReviewSessionKey(repository.workspace_id, item.number)
    setOpeningReviewKey(key)
    try {
      await onOpenInChat(repository, item)
    } finally {
      setOpeningReviewKey(null)
    }
  }

  const connectionById = new Map(
    (connections.data ?? []).map((connection) => [connection.id, connection]),
  )
  const editConnection = configTarget?.connection_id
    ? connectionById.get(configTarget.connection_id) ?? null
    : null
  const visibleCount = visibleRepositories.reduce(
    (count, repository) => count + repository.items.length,
    0,
  )

  if (selectedReview) {
    return (
      <ReviewDetails
        repository={selectedReview.repository}
        item={selectedReview.item}
        onBack={() => setSelectedReview(null)}
        onOpenInChat={onOpenInChat}
      />
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="shrink-0 border-b border-(--color-border) px-4 pb-3 pt-2">
        <div className="flex items-center gap-2">
          <GitPullRequest size={16} className="text-(--color-text-muted)" />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-(--color-text)">
              Pull Requests
            </h2>
            <p className="text-[11px] text-(--color-text-muted)">
              {reviews.isLoading
                ? 'Loading registered repositories…'
                : `${visibleCount} open across ${visibleRepositories.length} repositories · ${
                    scope === 'all'
                      ? 'all Coding repositories'
                      : projectId
                        ? 'current project'
                        : 'current workspace'
                  }`}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setManageOpen(true)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Manage Git server connections"
            title="Manage connections"
          >
            <KeyRound size={14} />
          </button>
          <button
            type="button"
            onClick={() => void reviews.refetch()}
            disabled={reviews.isFetching}
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
            aria-label="Refresh pull requests"
          >
            <RefreshCw
              size={14}
              className={reviews.isFetching ? 'animate-spin' : ''}
            />
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <SegmentedControl
            options={FILTERS}
            value={filter}
            onChange={setFilter}
            layoutId="pull-request-filter"
            ariaLabel="Filter pull requests"
          />
          <div className="relative min-w-36 flex-1">
            <Search
              size={13}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-(--color-text-subtle)"
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search reviews…"
              className="h-8 bg-(--bg-card) pl-8 text-xs"
            />
          </div>
          <NativeSelect
            value={repositoryFilter}
            onChange={(event) => setRepositoryFilter(event.target.value)}
            className="h-8 min-w-44 flex-1 bg-(--bg-card) text-xs"
            aria-label="Filter by repository"
          >
            <NativeSelectOption value="all">
              All repositories
            </NativeSelectOption>
            {(reviews.data?.repositories ?? []).map((repository) => (
              <NativeSelectOption
                key={repository.workspace_id}
                value={repository.workspace_id}
              >
                {repository.repository ?? repository.name}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
      </header>

      <div ref={contentRef} className="min-h-0 flex-1 overflow-y-auto">
        {reviews.isLoading && (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-(--color-text-muted)">
            <Loader2 size={16} className="animate-spin" />
            Loading pull requests…
          </div>
        )}
        {reviews.isError && (
          <div className="m-4 rounded-xl border border-(--color-error)/30 bg-(--color-error-subtle) p-4 text-sm text-(--color-error)">
            {reviews.error instanceof Error
              ? reviews.error.message
              : 'Unable to load pull requests.'}
          </div>
        )}
        {!reviews.isLoading &&
          !reviews.isError &&
          visibleRepositories.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center px-8 text-center">
              <GitPullRequest
                size={28}
                className="text-(--color-text-subtle)"
              />
              <p className="mt-3 text-sm font-medium text-(--color-text)">
                No coding repositories
              </p>
              <p className="mt-1 max-w-sm text-xs leading-5 text-(--color-text-muted)">
                Add a repository to Coding mode, then connect its Git server.
              </p>
            </div>
          )}
        {visibleRepositories.map((repository) => (
          <section
            key={repository.workspace_id}
            className="border-b border-(--color-border)"
          >
            <div className="sticky top-0 z-10 flex items-center gap-2 bg-(--bg-card)/95 px-4 py-2 backdrop-blur">
              {repository.provider === 'gitlab' ? (
                <GitMerge size={13} className="text-(--color-text-muted)" />
              ) : (
                <GitPullRequest
                  size={13}
                  className="text-(--color-text-muted)"
                />
              )}
              <span className="min-w-0 flex-1 truncate text-xs font-semibold text-(--color-text)">
                {repository.repository ?? repository.name}
              </span>
              <span className="text-[10px] text-(--color-text-subtle)">
                {providerLabel(
                  repository.provider ?? repository.detected_provider,
                )}{' '}
                · {repository.items.length}
              </span>
              <button
                type="button"
                onClick={() => setConfigTarget(repository)}
                className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
                aria-label={`Configure ${repository.name}`}
                title="Configure connection"
              >
                <Settings2 size={12} />
              </button>
            </div>
            {repository.error && (
              <div className="flex items-start gap-2 border-t border-(--color-border)/70 px-4 py-3">
                <AlertCircle
                  size={14}
                  className="mt-0.5 shrink-0 text-(--color-warning)"
                />
                <span className="min-w-0 flex-1 text-xs text-(--color-text-muted)">
                  <span className="block text-(--color-text-2)">
                    {repository.error}
                  </span>
                  <button
                    type="button"
                    onClick={() => setConfigTarget(repository)}
                    className="mt-1 text-(--color-accent) hover:underline"
                  >
                    {repository.connection_id
                      ? 'Update connection'
                      : 'Connect repository'}
                  </button>
                </span>
              </div>
            )}
            {!repository.error && repository.items.length === 0 && (
              <p className="border-t border-(--color-border)/70 px-4 py-3 text-xs text-(--color-text-muted)">
                No open {providerReviewName(repository.provider).toLowerCase()}s.
              </p>
            )}
            {repository.items.map((item) => (
              <ReviewRow
                key={item.number}
                repository={repository}
                item={item}
                provider={repository.provider}
                linked={linkedReviewKeys.has(
                  codeReviewSessionKey(repository.workspace_id, item.number),
                )}
                focused={
                  focusedReviewKey
                  === codeReviewSessionKey(repository.workspace_id, item.number)
                }
                opening={
                  openingReviewKey
                  === codeReviewSessionKey(repository.workspace_id, item.number)
                }
                onOpenInChat={openReviewInChat}
                onInspect={(targetRepository, targetItem) =>
                  setSelectedReview({
                    repository: targetRepository,
                    item: targetItem,
                  })
                }
              />
            ))}
          </section>
        ))}
      </div>

      {configTarget && (
        <ConnectionDialog
          key={`${configTarget.workspace_id}:${editConnection?.id ?? 'new'}`}
          target={configTarget}
          connection={editConnection}
          onClose={() => setConfigTarget(null)}
        />
      )}
      <ConnectionsDialog
        open={manageOpen}
        onClose={() => setManageOpen(false)}
        connections={connections.data ?? []}
      />
    </div>
  )
}
