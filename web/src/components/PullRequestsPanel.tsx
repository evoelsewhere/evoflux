import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileDiff,
  GitBranch,
  GitCommitHorizontal,
  GitMerge,
  GitPullRequest,
  KeyRound,
  Loader2,
  MessageCircle,
  Minus,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  Users,
  XCircle,
  Copy,
  type LucideIcon,
} from 'lucide-react'

import type {
  CodeReviewItem,
  CodeReviewActionInput,
  CodeReviewComment,
  CodeReviewContext,
  CodeReviewFile,
  GitServerConnection,
  GitServerConnectionInput,
  GitServerConnectionScope,
  GitServerProvider,
  RepositoryCodeReviews,
} from '@/api/types'
import { getCodeReviewImageUrl, gitJobs, gitPush } from '@/api/client'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from '@/components/ui/avatar'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
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
  useCreateCodeReviewMutation,
  useDeleteGitServerConnectionMutation,
  useGitServerConnectionsQuery,
  useSaveGitServerConnectionMutation,
  useTestGitServerConnectionMutation,
} from '@/queries'
import {
  useGitBranchesQuery,
  useGitRemotesQuery,
  useGitRepositoryQuery,
} from '@/queries/useGitQuery'
import { useTeamSessionsQuery } from '@/queries/useSessionsQuery'
import { formatRelativeDate } from '@/utils/format'
import { MarkdownBlock } from '@/utils/markdown'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'
import { GitActionSurface, type GitAction } from '@/components/git/GitActionMenu'
import type { PullRequestsScope } from '@/stores/useUIStore'
import { getIntlLocale } from '@/i18n'
import { parseUnifiedDiff } from '@/lib/unified-diff'

type ReviewFilter = 'open' | 'ready' | 'draft' | 'closed' | 'merged'

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
  { value: 'open', label: 'Open' },
  { value: 'ready', label: 'Ready' },
  { value: 'draft', label: 'Drafts' },
  { value: 'closed', label: 'Closed' },
  { value: 'merged', label: 'Merged' },
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

function authorInitials(author: string | null): string {
  if (!author) return '?'
  const parts = author.trim().split(/[\s._-]+/).filter(Boolean)
  if (parts.length === 0) return '?'
  return parts.slice(0, 2).map((part) => part[0]).join('').toUpperCase()
}

function ReviewAuthor({
  author,
  avatarUrl,
  compact = false,
}: {
  author: string | null
  avatarUrl: string | null
  compact?: boolean
}) {
  return (
    <span
      className="inline-flex min-w-0 items-center gap-1.5"
      title={author ?? 'Unknown author'}
    >
      <Avatar
        size="sm"
        className={cn(
          'ring-1 ring-(--color-border)',
          compact ? 'size-4' : 'size-5',
        )}
      >
        {avatarUrl && (
          <AvatarImage
            src={avatarUrl}
            alt=""
            referrerPolicy="no-referrer"
          />
        )}
        <AvatarFallback
          className={compact ? 'text-[8px] font-semibold' : 'text-[9px] font-semibold'}
        >
          {authorInitials(author)}
        </AvatarFallback>
      </Avatar>
      <span className="max-w-32 truncate">{author ?? 'Unknown author'}</span>
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
          {value.toLocaleString(getIntlLocale())}
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
  const actions: GitAction[] = [
    {
      label: 'Open review details',
      icon: <FileDiff size={12} />,
      onSelect: () => onInspect(repository, item),
    },
    {
      label: linked ? 'Continue review in chat' : 'Review in chat',
      icon: <MessageCircle size={12} />,
      onSelect: () => void onOpenInChat(repository, item),
      disabled: opening,
    },
  ]
  if (item.web_url) {
    actions.push(
      {
        label: 'Open in browser',
        icon: <ExternalLink size={12} />,
        onSelect: () => void openExternalUrl(item.web_url!),
        separatorBefore: true,
      },
      {
        label: 'Copy review URL',
        icon: <Copy size={12} />,
        onSelect: () => void navigator.clipboard.writeText(item.web_url!),
      },
    )
  }
  if (item.source_branch) {
    actions.push({
      label: 'Copy source branch',
      icon: <GitBranch size={12} />,
      onSelect: () => void navigator.clipboard.writeText(item.source_branch),
      separatorBefore: true,
    })
  }
  return (
    <GitActionSurface
      label={`#${item.number} ${item.title}`}
      actions={actions}
      dataReviewKey={reviewKey}
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
            className="inline-flex h-6 shrink-0 items-center gap-1 rounded-md border border-(--color-border) bg-(--bg-card) px-2 text-[11px] font-medium text-(--color-text-muted) shadow-sm transition-colors hover:border-(--color-accent)/40 hover:text-(--color-accent) disabled:opacity-60"
            title={linked ? 'Continue review chat' : 'Review in chat'}
          >
            {opening ? (
              <Loader2 size={11} className="animate-spin" />
            ) : (
              <MessageCircle size={11} />
            )}
            {linked ? 'Continue' : 'Review'}
          </button>
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-(--color-text-muted)">
          <span>#{item.number}</span>
          <StatusPill value={item.draft ? 'draft' : item.state || 'open'} />
          {(item.author || item.author_avatar_url) && (
            <ReviewAuthor
              author={item.author}
              avatarUrl={item.author_avatar_url}
              compact
            />
          )}
          {item.updated_at && <span>{formatRelativeDate(item.updated_at)}</span>}
          {item.comment_count !== null && (
            <span className="inline-flex items-center gap-1">
              <MessageCircle size={10} />
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
    </GitActionSurface>
  )
}

function ReviewCommentCard({
  comment,
  pending,
  transformImageSrc,
  onReply,
  onToggleResolved,
}: {
  comment: CodeReviewComment
  pending: boolean
  onReply: (comment: CodeReviewComment, body: string) => Promise<boolean>
  transformImageSrc: (src: string) => string
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
      <div className="mt-2 min-w-0 text-(--color-text-2) [&_.oa-prose]:text-xs [&_.oa-prose]:leading-5">
        <MarkdownBlock
          content={comment.body}
          allowHtml
          transformImageSrc={transformImageSrc}
        />
      </div>
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
                void onReply(comment, value).then((success) => {
                  if (success) setReply('')
                })
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

type InlineCommentTarget = {
  line: number
  side: 'LEFT' | 'RIGHT'
}

type ReviewLifecycleAction = 'merge' | 'close' | 'reopen'

const MERGE_METHODS: Record<GitServerProvider, ReadonlyArray<{ value: string; label: string }>> = {
  github: [
    { value: 'merge', label: 'Merge commit' },
    { value: 'squash', label: 'Squash and merge' },
    { value: 'rebase', label: 'Rebase and merge' },
  ],
  gitlab: [
    { value: 'merge', label: 'Merge commit' },
    { value: 'squash', label: 'Squash and merge' },
  ],
  bitbucket_cloud: [
    { value: 'merge_commit', label: 'Merge commit' },
    { value: 'squash', label: 'Squash' },
    { value: 'fast_forward', label: 'Fast-forward' },
  ],
  bitbucket_server: [],
  gitea: [
    { value: 'merge', label: 'Merge commit' },
    { value: 'squash', label: 'Squash and merge' },
    { value: 'rebase', label: 'Rebase' },
    { value: 'rebase-merge', label: 'Rebase then merge' },
  ],
  azure_devops: [
    { value: 'noFastForward', label: 'Merge commit' },
    { value: 'squash', label: 'Squash' },
    { value: 'rebase', label: 'Rebase' },
    { value: 'rebaseMerge', label: 'Rebase then merge' },
  ],
}

function ReviewLifecycleDialog({
  action,
  context,
  pending,
  onClose,
  onConfirm,
}: {
  action: ReviewLifecycleAction | null
  context: CodeReviewContext
  pending: boolean
  onClose: () => void
  onConfirm: (input: CodeReviewActionInput) => Promise<boolean>
}) {
  const mergeMethods = MERGE_METHODS[context.provider]
  const [mergeMethod, setMergeMethod] = useState('')
  const [commitTitle, setCommitTitle] = useState('')
  const mergeBlocked = context.draft || context.mergeability.conflicts || context.mergeability.merged

  const confirm = async () => {
    if (!action) return
    const success = await onConfirm(
      action === 'merge'
        ? {
            action: 'merge',
            merge_method: mergeMethod || undefined,
            commit_title: commitTitle.trim() || undefined,
          }
        : { action },
    )
    if (success) onClose()
  }

  const title = action === 'merge'
    ? 'Merge this review?'
    : action === 'close'
      ? 'Close this review?'
      : 'Reopen this review?'
  return (
    <Dialog open={action !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {action === 'merge'
              ? 'EvoFlux will refresh the provider state after this important action. Repository branch protections still apply.'
              : action === 'close'
                ? 'This stops the active review without deleting its branch or discussion.'
                : 'This restores the review to its provider’s active state.'}
          </DialogDescription>
        </DialogHeader>
        {action === 'merge' && (
          <div className="space-y-3">
            <div className="grid grid-cols-3 divide-x divide-(--color-border) overflow-hidden rounded-lg border border-(--color-border) text-center">
              <span className="px-2 py-2 text-[10px] text-(--color-text-muted)">
                <strong className="block text-xs capitalize text-(--color-text)">{context.checks.summary}</strong>
                checks
              </span>
              <span className="px-2 py-2 text-[10px] text-(--color-text-muted)">
                <strong className="block text-xs text-(--color-text)">{context.approvals.filter((item) => item.state === 'approved').length}</strong>
                approvals
              </span>
              <span className="px-2 py-2 text-[10px] text-(--color-text-muted)">
                <strong className={cn(
                  'block text-xs',
                  context.mergeability.conflicts ? 'text-(--color-error)' : 'text-(--color-success)',
                )}>
                  {context.mergeability.conflicts ? 'Conflicts' : 'No conflicts'}
                </strong>
                merge state
              </span>
            </div>
            {mergeBlocked && (
              <p className="rounded-lg bg-(--color-error-subtle) px-3 py-2 text-xs text-(--color-error)">
                {context.mergeability.merged
                  ? 'This review is already merged.'
                  : context.draft
                    ? 'Draft reviews must be marked ready before merging.'
                    : 'Resolve merge conflicts before merging.'}
              </p>
            )}
            <label className="block space-y-1.5 text-xs text-(--color-text-muted)">
              <span>Merge strategy</span>
              <NativeSelect
                value={mergeMethod}
                onChange={(event) => setMergeMethod(event.target.value)}
                className="w-full"
              >
                <NativeSelectOption value="">Provider default</NativeSelectOption>
                {mergeMethods.map((method) => (
                  <NativeSelectOption key={method.value} value={method.value}>
                    {method.label}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </label>
            <label className="block space-y-1.5 text-xs text-(--color-text-muted)">
              <span>Commit title (optional)</span>
              <Input
                value={commitTitle}
                onChange={(event) => setCommitTitle(event.target.value)}
                placeholder="Use provider default"
              />
            </label>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            variant={action === 'close' ? 'destructive' : 'default'}
            disabled={pending || (action === 'merge' && mergeBlocked)}
            onClick={() => void confirm()}
          >
            {pending && <Loader2 size={13} className="animate-spin" />}
            {action === 'merge' ? 'Merge review' : action === 'close' ? 'Close review' : 'Reopen review'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function reviewFileStatusTone(status: string): string {
  if (status === 'added') return 'bg-(--color-success-subtle) text-(--color-success)'
  if (status === 'deleted') return 'bg-(--color-error-subtle) text-(--color-error)'
  if (status === 'renamed' || status === 'copied') return 'bg-(--accent-blue-soft) text-(--accent-blue)'
  return 'bg-(--color-warning-subtle) text-(--color-warning)'
}

function ReviewFileCard({
  file,
  pending,
  onComment,
}: {
  file: CodeReviewFile
  pending: boolean
  onComment: (
    file: CodeReviewFile,
    target: InlineCommentTarget,
    body: string,
  ) => Promise<boolean>
}) {
  const [expanded, setExpanded] = useState(false)
  const [target, setTarget] = useState<InlineCommentTarget | null>(null)
  const [body, setBody] = useState('')
  const hunks = useMemo(() => parseUnifiedDiff(file.patch ?? ''), [file.patch])

  const submit = async () => {
    if (!target || !body.trim()) return
    if (await onComment(file, target, body.trim())) {
      setBody('')
      setTarget(null)
    }
  }

  return (
    <article className="overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-card)">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-(--bg-key)/60"
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <FileDiff size={13} className="shrink-0 text-(--color-text-muted)" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-[11px] text-(--color-text)">
            {file.path}
          </span>
          {file.old_path && (
            <span className="block truncate font-mono text-[10px] text-(--color-text-subtle)">
              from {file.old_path}
            </span>
          )}
        </span>
        {file.additions !== null && (
          <span className="text-[10px] tabular-nums text-(--color-success)">+{file.additions}</span>
        )}
        {file.deletions !== null && (
          <span className="text-[10px] tabular-nums text-(--color-error)">-{file.deletions}</span>
        )}
        <span className={cn(
          'rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase',
          reviewFileStatusTone(file.status),
        )}>
          {file.status}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-(--color-border)">
          {hunks.length === 0 ? (
            <p className="px-3 py-4 text-center text-[11px] text-(--color-text-muted)">
              {file.binary
                ? 'Binary file — no text preview is available.'
                : 'This provider returned file metadata without an inline patch. Review it in chat or open the provider view for the full diff.'}
            </p>
          ) : (
            <div className="overflow-x-auto bg-(--bg-page)">
              {hunks.map((hunk, hunkIndex) => {
                let oldLine = hunk.oldStart
                let newLine = hunk.newStart
                return (
                  <div key={`${hunk.header}:${hunkIndex}`} className="min-w-max">
                    <div className="sticky left-0 border-y border-(--color-border) bg-(--accent-blue-soft) px-3 py-1 font-mono text-[10px] text-(--accent-blue)">
                      {hunk.header}
                    </div>
                    {hunk.lines.map((line, lineIndex) => {
                      const oldNumber = line.type === 'add' || line.type === 'info' ? null : oldLine++
                      const newNumber = line.type === 'del' || line.type === 'info' ? null : newLine++
                      const side = line.type === 'del' ? 'LEFT' : 'RIGHT'
                      const lineNumber = side === 'LEFT' ? oldNumber : newNumber
                      const selectable = Boolean(
                        file.can_comment && lineNumber && line.type !== 'info',
                      )
                      const selected = target?.line === lineNumber && target.side === side
                      return (
                        <button
                          type="button"
                          key={`${hunkIndex}:${lineIndex}`}
                          disabled={!selectable}
                          onClick={() => {
                            if (lineNumber) setTarget({ line: lineNumber, side })
                          }}
                          className={cn(
                            'grid w-full grid-cols-[3rem_3rem_1.25rem_minmax(20rem,1fr)] text-left font-mono text-[11px] leading-5',
                            line.type === 'add' && 'bg-(--color-success-subtle)',
                            line.type === 'del' && 'bg-(--color-error-subtle)',
                            selectable && 'cursor-pointer hover:ring-1 hover:ring-inset hover:ring-(--color-accent)/45',
                            selected && 'ring-1 ring-inset ring-(--color-accent)',
                          )}
                          title={selectable ? `Comment on ${file.path}:${lineNumber}` : undefined}
                        >
                          <span className="select-none border-r border-(--color-border)/60 px-1 text-right text-(--color-text-subtle)">
                            {oldNumber ?? ''}
                          </span>
                          <span className="select-none border-r border-(--color-border)/60 px-1 text-right text-(--color-text-subtle)">
                            {newNumber ?? ''}
                          </span>
                          <span className={cn(
                            'select-none text-center',
                            line.type === 'add' && 'text-(--color-success)',
                            line.type === 'del' && 'text-(--color-error)',
                          )}>
                            {line.type === 'add' ? '+' : line.type === 'del' ? '-' : ' '}
                          </span>
                          <span className="whitespace-pre px-1.5 text-(--color-text-2)">{line.content || ' '}</span>
                        </button>
                      )
                    })}
                  </div>
                )
              })}
            </div>
          )}
          {file.patch_truncated && (
            <p className="border-t border-(--color-border) px-3 py-2 text-[10px] text-(--color-warning)">
              Patch preview was truncated to keep review context responsive.
            </p>
          )}
          {target && (
            <div className="space-y-2 border-t border-(--color-border) bg-(--bg-card) p-3">
              <p className="text-[10px] text-(--color-text-muted)">
                Inline comment on <span className="font-mono text-(--color-text)">{file.path}:{target.line}</span>
              </p>
              <Textarea
                value={body}
                onChange={(event) => setBody(event.target.value)}
                placeholder="Write an evidence-based inline comment…"
                className="min-h-20 text-xs"
                autoFocus
              />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" onClick={() => setTarget(null)}>
                  Cancel
                </Button>
                <Button size="sm" disabled={pending || !body.trim()} onClick={() => void submit()}>
                  {pending ? <Loader2 size={12} className="animate-spin" /> : <MessageCircle size={12} />}
                  Add inline comment
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </article>
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
  const [lifecycleAction, setLifecycleAction] = useState<ReviewLifecycleAction | null>(null)
  const pushToast = useToastStore((state) => state.push)
  const transformImageSrc = useMemo(
    () => (src: string) => getCodeReviewImageUrl(repository.workspace_id, src),
    [repository.workspace_id],
  )

  const mutate = async (
    input: Parameters<typeof action.mutateAsync>[0],
  ): Promise<boolean> => {
    try {
      await action.mutateAsync(input)
      await detail.refetch()
      return true
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Review action failed',
        description: error instanceof Error ? error.message : String(error),
      })
      return false
    }
  }
  const capabilities = detail.data?.capabilities ?? {}
  const summary = detail.data?.summary
  const mergeability = detail.data
    ? mergeabilityStatus(detail.data.mergeability)
    : null
  const approvedCount = detail.data?.approvals.filter(
    (approval) => approval.state === 'approved',
  ).length ?? 0
  const normalizedState = detail.data?.state.toLowerCase() ?? item.state.toLowerCase()
  const isOpen = ['open', 'opened', 'active'].includes(normalizedState)
  const isClosed = ['closed', 'declined', 'abandoned'].includes(normalizedState)
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
              {(summary?.author ?? item.author ?? item.author_avatar_url) && (
                <ReviewAuthor
                  author={summary?.author ?? item.author}
                  avatarUrl={item.author_avatar_url}
                />
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
          {capabilities.merge && isOpen && !detail.data?.mergeability.merged && (
            <Button
              size="sm"
              disabled={action.isPending}
              onClick={() => setLifecycleAction('merge')}
            >
              <GitMerge size={13} />
              Merge
            </Button>
          )}
          {capabilities.close && isOpen && (
            <Button
              size="sm"
              variant="destructive"
              disabled={action.isPending}
              onClick={() => setLifecycleAction('close')}
            >
              <XCircle size={13} />
              Close
            </Button>
          )}
          {capabilities.reopen && isClosed && (
            <Button
              size="sm"
              variant="outline"
              disabled={action.isPending}
              onClick={() => setLifecycleAction('reopen')}
            >
              <RefreshCw size={13} />
              Reopen
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => void onOpenInChat(repository, item)}
          >
            <MessageCircle size={13} />
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
                <div className="min-w-0 text-(--color-text-2) [&_.oa-prose]:text-xs [&_.oa-prose]:leading-5">
                  <MarkdownBlock
                    content={summary.description}
                    allowHtml
                    transformImageSrc={transformImageSrc}
                  />
                </div>
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
              <div className="flex items-center justify-between gap-3">
                <h4 className="text-xs font-semibold text-(--color-text)">
                  Files changed
                </h4>
                <span className="text-[10px] text-(--color-text-subtle)">
                  {detail.data.files?.length ?? summary?.changed_files ?? 0} files
                </span>
              </div>
              <div className="mt-2 space-y-2">
                {(detail.data.files ?? []).map((file) => (
                  <ReviewFileCard
                    key={`${file.old_path ?? ''}:${file.path}`}
                    file={file}
                    pending={action.isPending}
                    onComment={(targetFile, lineTarget, body) =>
                      mutate({
                        action: 'inline_comment',
                        body,
                        path: targetFile.path,
                        old_path: targetFile.old_path ?? undefined,
                        line: lineTarget.line,
                        side: lineTarget.side,
                        commit_id: targetFile.commit_id ?? undefined,
                        base_commit_id: targetFile.base_commit_id ?? undefined,
                        start_commit_id: targetFile.start_commit_id ?? undefined,
                      })
                    }
                  />
                ))}
                {(detail.data.files?.length ?? 0) === 0 && (
                  <p className="rounded-lg border border-dashed border-(--color-border) p-4 text-center text-xs text-(--color-text-muted)">
                    No changed-file metadata was returned by this provider.
                  </p>
                )}
                {detail.data.files_truncated > 0 && (
                  <p className="rounded-lg border border-(--color-warning)/35 bg-(--color-warning-subtle) px-3 py-2 text-[11px] text-(--color-warning)">
                    {detail.data.files_truncated} additional files are omitted from this bounded preview. Review the complete change set in chat.
                  </p>
                )}
              </div>
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
                    }).then((success) => {
                      if (success) setComment('')
                    })
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
                    transformImageSrc={transformImageSrc}
                    onReply={(target, body) =>
                      mutate({
                        action: 'reply',
                        thread_id: target.thread_id,
                        body,
                      })
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
                {detail.data.comments_truncated > 0 && (
                  <p className="rounded-lg border border-(--color-warning)/35 bg-(--color-warning-subtle) px-3 py-2 text-[11px] text-(--color-warning)">
                    {detail.data.comments_truncated} older comments are omitted from this bounded preview. Continue in chat for the complete provider context.
                  </p>
                )}
              </div>
            </section>
          </>
        )}
      </div>
      {detail.data && (
        <ReviewLifecycleDialog
          key={`${lifecycleAction ?? 'closed'}:${detail.data.provider}`}
          action={lifecycleAction}
          context={detail.data}
          pending={action.isPending}
          onClose={() => setLifecycleAction(null)}
          onConfirm={mutate}
        />
      )}
    </div>
  )
}

interface ConnectionDialogProps {
  target: RepositoryCodeReviews
  connection: GitServerConnection | null
  connectionLoading?: boolean
  onClose: () => void
}

function ConnectionDetail({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="grid gap-0.5 px-3 py-2.5 sm:grid-cols-[8.5rem_minmax(0,1fr)] sm:items-center sm:gap-3">
      <dt className="text-xs text-(--color-text-muted)">{label}</dt>
      <dd className="min-w-0 break-words text-sm font-medium text-(--color-text)">
        {children}
      </dd>
    </div>
  )
}

export function GitServerConnectionSummary({
  connection,
  onClose,
  onEdit,
}: {
  connection: GitServerConnection
  onClose: () => void
  onEdit: () => void
}) {
  const scopeLabel = SCOPES.find((scope) => scope.value === connection.scope)?.label
    ?? connection.scope

  return (
    <>
      <section
        aria-label="Saved Git server connection"
        className="overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-page)"
      >
        <div className="flex items-center gap-3 border-b border-(--color-border) px-3 py-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-(--color-success-subtle) text-(--color-success)">
            <KeyRound size={16} aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-(--color-text)">
              {connection.name}
            </span>
            <span className="mt-0.5 flex items-center gap-1 text-xs text-(--color-success)">
              <CheckCircle2 size={12} aria-hidden="true" />
              Configured
            </span>
          </span>
        </div>
        <dl className="divide-y divide-(--color-border)">
          <ConnectionDetail label="Provider">
            {providerLabel(connection.provider)}
          </ConnectionDetail>
          <ConnectionDetail label="Git server">
            {connection.domain}
          </ConnectionDetail>
          <ConnectionDetail label="API endpoint">
            <span className="font-mono text-xs">{connection.base_url}</span>
          </ConnectionDetail>
          <ConnectionDetail label="Credential scope">
            {scopeLabel}
          </ConnectionDetail>
          <ConnectionDetail label="Access token">
            <span className={connection.has_token ? 'text-(--color-success)' : 'text-(--color-error)'}>
              {connection.has_token ? 'Saved securely' : 'Not configured'}
            </span>
          </ConnectionDetail>
          {connection.username && (
            <ConnectionDetail label="Username">
              {connection.username}
            </ConnectionDetail>
          )}
          <ConnectionDetail label="TLS verification">
            {connection.verify_ssl ? 'Enabled' : 'Disabled'}
          </ConnectionDetail>
          <ConnectionDetail label="Last updated">
            {formatRelativeDate(connection.updated_at)}
          </ConnectionDetail>
        </dl>
      </section>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>Close</Button>
        <Button variant="outline" onClick={onEdit}>
          <Settings2 size={13} aria-hidden="true" />
          Edit connection
        </Button>
      </DialogFooter>
    </>
  )
}

export function ConnectionDialog({
  target,
  connection,
  connectionLoading = false,
  onClose,
}: ConnectionDialogProps) {
  const save = useSaveGitServerConnectionMutation()
  const test = useTestGitServerConnectionMutation()
  const [editing, setEditing] = useState(!connection)
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
  const expectsSavedConnection = Boolean(target.connection_id)
  const showSavedConnection = connection !== null && !editing

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {showSavedConnection
              ? 'Git server connection'
              : connection ? 'Edit Git server connection' : 'Connect Git server'}
          </DialogTitle>
          <DialogDescription>
            {showSavedConnection
              ? `${target.repository ?? target.name} is using this saved connection for pull requests and HTTPS Git sync.`
              : `One saved credential for pull requests and HTTPS Git sync in ${target.repository ?? target.name}. It is stored separately from repository metadata.`}
          </DialogDescription>
        </DialogHeader>

        {showSavedConnection && (
          <GitServerConnectionSummary
            connection={connection}
            onClose={onClose}
            onEdit={() => setEditing(true)}
          />
        )}

        {!connection && expectsSavedConnection && (
          <>
            <div className="flex min-h-28 items-center justify-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-page) px-4 text-sm text-(--color-text-muted)">
              {connectionLoading ? (
                <>
                  <Loader2 size={15} className="animate-spin" />
                  Loading saved connection…
                </>
              ) : (
                <>
                  <AlertCircle size={15} className="text-(--color-warning)" />
                  Saved connection details are unavailable. Refresh connections and try again.
                </>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={onClose}>Close</Button>
            </DialogFooter>
          </>
        )}

        {!showSavedConnection && (!expectsSavedConnection || connection) && (
          <>
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
                Git access token
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
              Used for review APIs and for HTTPS fetch, pull, and push. SSH
              remotes continue to use your SSH agent.
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
          </>
        )}
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
            Shared credentials apply by Git hostname and power both remote
            reviews and HTTPS Git sync. Repository-scoped credentials take
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

function CreateReviewDialog({
  target,
  onClose,
}: {
  target: RepositoryCodeReviews | null
  onClose: () => void
}) {
  const workspace = target?.workspace ?? ''
  const repository = useGitRepositoryQuery(workspace, Boolean(target))
  const branches = useGitBranchesQuery(workspace, Boolean(target))
  const remotes = useGitRemotesQuery(workspace, Boolean(target))
  const create = useCreateCodeReviewMutation(target?.workspace_id ?? '')
  const push = useToastStore((state) => state.push)
  const [form, setForm] = useState({
    title: '',
    body: '',
    sourceBranch: '',
    targetBranch: '',
  })
  const [publishing, setPublishing] = useState(false)

  const localBranches = useMemo(
    () => (branches.data ?? []).filter((branch) => branch.remote === null),
    [branches.data],
  )
  const remoteBranches = useMemo(
    () => (branches.data ?? []).filter((branch) => branch.remote !== null),
    [branches.data],
  )

  const detectedSource = repository.data?.branch ?? ''
  const likelyTarget =
    localBranches.find((branch) => branch.name === 'main')?.name
    ?? localBranches.find((branch) => branch.name === 'master')?.name
    ?? target?.items[0]?.target_branch
    ?? 'main'
  const sourceBranch = form.sourceBranch || detectedSource
  const targetBranch = form.targetBranch || likelyTarget
  const localSourceExists = localBranches.some((branch) => branch.name === sourceBranch)
  const sourcePublished = remoteBranches.some((branch) =>
    branch.name.endsWith(`/${sourceBranch}`),
  )
  const upstreamRemote = repository.data?.upstream?.split('/', 1)[0]
  const publishRemote =
    (remotes.data ?? []).find((remote) => remote.name === upstreamRemote)?.name
    ?? remotes.data?.find((remote) => remote.name === 'origin')?.name
    ?? remotes.data?.[0]?.name

  const waitForPush = async () => {
    const deadline = Date.now() + 5 * 60_000
    while (Date.now() < deadline) {
      const job = await gitJobs(workspace)
      if (!job) throw new Error('The Git push job disappeared before completion.')
      if (job.op !== 'push') {
        throw new Error(`A ${job.op} operation is already running for this repository.`)
      }
      if (job.status === 'done') return
      if (job.status !== 'running') {
        throw new Error(job.error || `Git push ended with status ${job.status}.`)
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500))
    }
    throw new Error('Timed out waiting for the source branch to finish pushing.')
  }

  const submit = async () => {
    if (!target) return
    try {
      if (!sourcePublished) {
        if (!localSourceExists) {
          throw new Error(`Local source branch '${sourceBranch}' does not exist.`)
        }
        if (!publishRemote) {
          throw new Error('Add a Git remote before creating this review.')
        }
        setPublishing(true)
        const job = await gitPush(workspace, {
          remote: publishRemote,
          branch: sourceBranch,
          setUpstream: true,
        })
        if (job.op !== 'push') {
          throw new Error(`A ${job.op} operation is already running for this repository.`)
        }
        if (job.status === 'running') await waitForPush()
        else if (job.status !== 'done') {
          throw new Error(job.error || `Git push ended with status ${job.status}.`)
        }
      }
      const created = await create.mutateAsync({
        title: form.title.trim(),
        body: form.body.trim(),
        source_branch: sourceBranch.trim(),
        target_branch: targetBranch.trim(),
      })
      push({
        tone: 'success',
        title: `${providerReviewName(target.provider)} created`,
        description: created.web_url || `#${created.number} is now open.`,
      })
      onClose()
    } catch (error) {
      push({
        tone: 'error',
        title: `Could not create ${providerReviewName(target.provider).toLowerCase()}`,
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setPublishing(false)
    }
  }

  return (
    <Dialog open={Boolean(target)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Create {providerReviewName(target?.provider ?? null).toLowerCase()}</DialogTitle>
          <DialogDescription>
            EvoFlux publishes the source branch when needed, then creates the review through the saved Git server connection.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1.5 text-xs text-(--color-text-muted)">
              <span>Source branch</span>
              <Input
                value={sourceBranch}
                onChange={(event) => setForm((current) => ({
                  ...current,
                  sourceBranch: event.target.value,
                }))}
                list="create-review-branches"
                placeholder="feature/my-change"
              />
            </label>
            <label className="space-y-1.5 text-xs text-(--color-text-muted)">
              <span>Target branch</span>
              <Input
                value={targetBranch}
                onChange={(event) => setForm((current) => ({
                  ...current,
                  targetBranch: event.target.value,
                }))}
                list="create-review-branches"
                placeholder="main"
              />
            </label>
            <datalist id="create-review-branches">
              {localBranches.map((branch) => (
                <option key={branch.name} value={branch.name} />
              ))}
            </datalist>
          </div>
          {!sourcePublished && sourceBranch && (
            <div className={cn(
              'rounded-lg border px-3 py-2 text-xs',
              localSourceExists && publishRemote
                ? 'border-(--color-accent)/30 bg-(--color-accent)/8 text-(--color-text-muted)'
                : 'border-(--color-warning)/35 bg-(--color-warning-subtle) text-(--color-warning)',
            )}>
              {localSourceExists && publishRemote
                ? `The branch will be pushed to ${publishRemote} before the review is created.`
                : !localSourceExists
                  ? `Local branch '${sourceBranch}' was not found.`
                  : 'Add a Git remote before creating this review.'}
            </div>
          )}
          <label className="block space-y-1.5 text-xs text-(--color-text-muted)">
            <span>Title</span>
            <Input
              value={form.title}
              onChange={(event) => setForm((current) => ({
                ...current,
                title: event.target.value,
              }))}
              placeholder="Describe the change"
              autoFocus
            />
          </label>
          <label className="block space-y-1.5 text-xs text-(--color-text-muted)">
            <span>Description</span>
            <Textarea
              value={form.body}
              onChange={(event) => setForm((current) => ({
                ...current,
                body: event.target.value,
              }))}
              placeholder="Summary, validation, and rollout notes…"
              className="min-h-32"
            />
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            onClick={() => void submit()}
            disabled={
              create.isPending
              || publishing
              || !form.title.trim()
              || !sourceBranch.trim()
              || !targetBranch.trim()
              || sourceBranch.trim() === targetBranch.trim()
              || (!sourcePublished && (!localSourceExists || !publishRemote))
            }
          >
            <GitPullRequest size={13} aria-hidden="true" />
            {publishing
              ? 'Pushing branch…'
              : create.isPending
                ? 'Creating…'
                : sourcePublished
                  ? 'Create review'
                  : 'Push & create review'}
          </Button>
        </DialogFooter>
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
  const [filter, setFilter] = useState<ReviewFilter>('open')
  const providerState: 'open' | 'closed' | 'merged' =
    filter === 'closed' || filter === 'merged' ? filter : 'open'
  const reviewScope =
    scope === 'session'
      ? projectId
        ? { projectId, state: providerState }
        : { workspace, state: providerState }
      : { state: providerState }
  const reviews = useCodeReviewsQuery(open, reviewScope)
  const connections = useGitServerConnectionsQuery(open)
  const codingSessions = useTeamSessionsQuery('coding')
  const contentRef = useRef<HTMLDivElement>(null)
  const [repositoryFilter, setRepositoryFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [openingReviewKey, setOpeningReviewKey] = useState<string | null>(null)
  const [configTarget, setConfigTarget] =
    useState<RepositoryCodeReviews | null>(null)
  const [manageOpen, setManageOpen] = useState(false)
  const [createTarget, setCreateTarget] =
    useState<RepositoryCodeReviews | null>(null)
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
    setFilter('open')
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
      <header className="shrink-0 border-b border-(--color-border) px-3 py-2">
        <div className="flex items-center gap-2">
          <p className="min-w-0 flex-1 truncate text-[11px] text-(--color-text-muted)">
            {reviews.isLoading
              ? 'Loading registered repositories…'
              : `${visibleCount} ${providerState} · ${visibleRepositories.length} repositories · ${
                  scope === 'all'
                    ? 'all Coding repositories'
                    : projectId
                      ? 'current project'
                      : 'current workspace'
                }`}
          </p>
          <button
            type="button"
            onClick={() => setManageOpen(true)}
            className="flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-card) px-2 text-[10px] font-medium text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Manage Git server connections"
            title="Manage connections"
          >
            <KeyRound size={12} />
            Connections
          </button>
          <button
            type="button"
            onClick={() => void reviews.refetch()}
            disabled={reviews.isFetching}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-card) text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
            aria-label="Refresh pull requests"
          >
            <RefreshCw
              size={12}
              className={reviews.isFetching ? 'animate-spin' : ''}
            />
          </button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
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
          <div className="m-4 rounded-xl border border-(--color-error)/35 bg-(--color-error-subtle) p-4 text-sm text-(--color-error)">
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
              {!repository.error && repository.connection_id && (
                <button
                  type="button"
                  onClick={() => setCreateTarget(repository)}
                  className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
                  aria-label={`Create review for ${repository.name}`}
                  title={`Create ${providerReviewName(repository.provider).toLowerCase()}`}
                >
                  <Plus size={12} />
                </button>
              )}
              {repository.remote_url && (
                <button
                  type="button"
                  onClick={() => setConfigTarget(repository)}
                  className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
                  aria-label={`Configure ${repository.name}`}
                  title="Configure connection"
                >
                  <Settings2 size={12} />
                </button>
              )}
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
                  {repository.remote_url && (
                    <button
                      type="button"
                      onClick={() => setConfigTarget(repository)}
                      className="mt-1 text-(--color-accent) hover:underline"
                    >
                      {repository.connection_id
                        ? 'Update connection'
                        : 'Connect repository'}
                    </button>
                  )}
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
          connectionLoading={connections.isLoading || connections.isFetching}
          onClose={() => setConfigTarget(null)}
        />
      )}
      <ConnectionsDialog
        open={manageOpen}
        onClose={() => setManageOpen(false)}
        connections={connections.data ?? []}
      />
      <CreateReviewDialog
        key={createTarget?.workspace_id ?? 'closed'}
        target={createTarget}
        onClose={() => setCreateTarget(null)}
      />
    </div>
  )
}
