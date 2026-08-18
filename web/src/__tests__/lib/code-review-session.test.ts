import { describe, expect, it } from 'vitest'

import type { CodeReviewItem, RepositoryCodeReviews } from '@/api/types'
import {
  codeReviewSessionPrompt,
  codeReviewSessionTags,
  parseCodeReviewSessionTags,
} from '@/lib/code-review-session'

const repository: RepositoryCodeReviews = {
  workspace_id: 'workspace-1',
  project_id: null,
  workspace: '/repo',
  name: 'repo',
  remote_url: 'git@github.com:acme/repo.git',
  repository: 'acme/repo',
  detected_provider: 'github',
  suggested_domain: 'https://github.com',
  suggested_base_url: 'https://api.github.com',
  connection_id: 'connection-1',
  provider: 'github',
  items: [],
  error: null,
}

const item: CodeReviewItem = {
  number: 42,
  title: 'Ship review workflow',
  state: 'open',
  draft: false,
  author: 'octocat',
  author_avatar_url: null,
  source_branch: 'feature',
  target_branch: 'main',
  updated_at: '2026-08-18T00:00:00Z',
  web_url: 'https://github.com/acme/repo/pull/42',
  labels: ['review'],
  review_status: null,
  pipeline_status: 'success',
  comment_count: 0,
}

describe('code review sessions', () => {
  it('round-trips the provider-neutral review identity through tags', () => {
    expect(parseCodeReviewSessionTags(codeReviewSessionTags(repository, item))).toEqual({
      workspaceId: 'workspace-1',
      number: 42,
    })
  })

  it('grounds a new AI review in current provider state and keeps it read-only', () => {
    const prompt = codeReviewSessionPrompt(repository, item)

    expect(prompt).toContain('get_code_review(number=42, repository="acme/repo")')
    expect(prompt).toContain('current head commit')
    expect(prompt).toContain('Do not publish a comment')
  })
})
