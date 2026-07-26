import type {
  CodeReviewItem,
  GitServerProvider,
  RepositoryCodeReviews,
} from '@/api/types'

const REVIEW_SESSION_TAG = 'code-review'
const REVIEW_CONTEXT_PREFIX = 'code-review:v1:'

export interface CodeReviewSessionContext {
  workspaceId: string
  number: number
}

export function codeReviewSessionKey(
  workspaceId: string,
  number: number,
): string {
  return `${workspaceId}:${number}`
}

export function codeReviewSessionTags(
  repository: RepositoryCodeReviews,
  item: CodeReviewItem,
): string[] {
  return [
    REVIEW_SESSION_TAG,
    `${REVIEW_CONTEXT_PREFIX}${codeReviewSessionKey(repository.workspace_id, item.number)}`,
  ]
}

export function parseCodeReviewSessionTags(
  tags: readonly string[] | null | undefined,
): CodeReviewSessionContext | null {
  const contextTag = tags?.find((tag) => tag.startsWith(REVIEW_CONTEXT_PREFIX))
  if (!contextTag) return null
  const encoded = contextTag.slice(REVIEW_CONTEXT_PREFIX.length)
  const separator = encoded.lastIndexOf(':')
  if (separator <= 0) return null
  const number = Number(encoded.slice(separator + 1))
  if (!Number.isSafeInteger(number) || number <= 0) return null
  return {
    workspaceId: encoded.slice(0, separator),
    number,
  }
}

function reviewKind(provider: GitServerProvider | null): string {
  return provider === 'gitlab' ? 'merge request' : 'pull request'
}

export function codeReviewSessionPrompt(
  repository: RepositoryCodeReviews,
  item: CodeReviewItem,
): string {
  const provider = repository.provider ?? repository.detected_provider
  const kind = reviewKind(provider)
  const lines = [
    `Review ${kind} #${item.number}: ${item.title}`,
    '',
    'Code review context:',
    `- Repository: ${repository.repository ?? repository.name}`,
    `- Provider: ${provider ?? 'unknown Git server'}`,
    `- Branches: ${item.source_branch || 'unknown'} -> ${item.target_branch || 'unknown'}`,
  ]
  if (item.author) lines.push(`- Author: ${item.author}`)
  if (item.web_url) lines.push(`- Review URL: ${item.web_url}`)
  if (item.labels.length > 0) lines.push(`- Labels: ${item.labels.join(', ')}`)
  if (item.review_status) lines.push(`- Review status: ${item.review_status}`)
  if (item.pipeline_status) lines.push(`- Pipeline status: ${item.pipeline_status}`)
  lines.push(
    '',
    'Inspect the local repository and the full diff against the target branch. Identify correctness issues, regressions, security or performance risks, and missing tests. Start with an evidence-based review summary, then help me implement fixes when appropriate.',
  )
  return lines.join('\n')
}
