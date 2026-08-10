import fuzzysort from 'fuzzysort'

import type { HelpArticle } from './types'

export interface HelpSearchHit {
  article: HelpArticle
  score: number
}

function haystack(article: HelpArticle): string {
  const blockText = article.blocks
    .map((block) => {
      if (block.type === 'p') return block.text
      if (block.type === 'heading') return block.text
      if (block.type === 'code') {
        return `${block.caption ?? ''} ${block.language ?? ''} ${block.code}`
      }
      if (block.type === 'table') {
        return [...block.columns, ...block.rows.flat()].join(' ')
      }
      if (block.type === 'callout') return `${block.title} ${block.text}`
      if (block.type === 'tips') return block.items.join(' ')
      if (block.type === 'shortcuts') {
        return block.rows.map((row) => `${row.keys} ${row.action}`).join(' ')
      }
      return block.commands.map((row) => `${row.cmd} ${row.desc}`).join(' ')
    })
    .join(' ')
  return [
    article.title,
    article.summary,
    article.setup ?? '',
    ...(article.tricks ?? []),
    article.keywords.join(' '),
    blockText,
  ].join('\n')
}

/** Rank articles for a query. Empty / whitespace query returns []. */
export function searchHelpArticles(
  articles: readonly HelpArticle[],
  query: string,
): HelpSearchHit[] {
  const q = query.trim()
  if (!q) return []

  const indexed = articles.map((article) => ({
    article,
    haystack: haystack(article),
  }))

  return fuzzysort
    .go(q, indexed, {
      key: 'haystack',
      // Match Settings → Providers model search: discard weak fuzzy noise.
      threshold: 0.2,
      limit: 80,
    })
    .map((result) => ({
      article: result.obj.article,
      score: result.score,
    }))
}

export function filterArticlesByCategory(
  articles: readonly HelpArticle[],
  categoryId: string | null,
): HelpArticle[] {
  if (!categoryId) return [...articles]
  return articles.filter((article) => article.category === categoryId)
}
