import { describe, expect, it } from 'vitest'

import {
  HELP_ARTICLES,
  HELP_CATEGORIES,
  filterArticlesByCategory,
  getHelpArticles,
  getHelpCategories,
  searchHelpArticles,
} from '@/help'

describe('help catalog', () => {
  it('covers every category with at least one article', () => {
    for (const category of HELP_CATEGORIES) {
      const articles = HELP_ARTICLES.filter((article) => article.category === category.id)
      expect(articles.length, category.id).toBeGreaterThan(0)
    }
  })

  it('keeps unique article ids', () => {
    const ids = HELP_ARTICLES.map((article) => article.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('keeps the same article ids across en / vi / ja', () => {
    const enIds = getHelpArticles('en').map((article) => article.id).sort()
    const viIds = getHelpArticles('vi').map((article) => article.id).sort()
    const jaIds = getHelpArticles('ja').map((article) => article.id).sort()
    expect(viIds).toEqual(enIds)
    expect(jaIds).toEqual(enIds)
    expect(getHelpCategories('vi')).toHaveLength(getHelpCategories('en').length)
    expect(getHelpCategories('ja')).toHaveLength(getHelpCategories('en').length)
  })

  it('localizes titles for Vietnamese and Japanese', () => {
    expect(getHelpArticles('vi').find((a) => a.id === 'getting-started')?.title).toMatch(
      /EvoFlux|Bắt đầu/,
    )
    expect(getHelpArticles('ja').find((a) => a.id === 'getting-started')?.title).toMatch(
      /EvoFlux|はじめ/,
    )
    expect(getHelpArticles('en').find((a) => a.id === 'getting-started')?.title).toMatch(
      /Getting started/,
    )
  })
})

describe('searchHelpArticles', () => {
  it('returns empty results for blank queries', () => {
    expect(searchHelpArticles(HELP_ARTICLES, '   ')).toEqual([])
  })

  it('finds folders by English keyword', () => {
    const hits = searchHelpArticles(HELP_ARTICLES, 'folder drag')
    expect(hits.some((hit) => hit.article.id === 'sessions-folders')).toBe(true)
  })

  it('finds goal mode via slash alias', () => {
    const hits = searchHelpArticles(HELP_ARTICLES, '/goal')
    expect(hits.some((hit) => hit.article.id === 'slash-goal')).toBe(true)
  })

  it('matches Vietnamese search in the Vietnamese corpus', () => {
    const hits = searchHelpArticles(getHelpArticles('vi'), 'thư mục')
    expect(hits.some((hit) => hit.article.id === 'sessions-folders')).toBe(true)
  })

  it('matches Japanese search in the Japanese corpus', () => {
    const hits = searchHelpArticles(getHelpArticles('ja'), 'フォルダ')
    expect(hits.some((hit) => hit.article.id === 'sessions-folders')).toBe(true)
  })

  it('filters by category when not searching', () => {
    const coding = filterArticlesByCategory(HELP_ARTICLES, 'coding')
    expect(coding.every((article) => article.category === 'coding')).toBe(true)
    expect(coding.length).toBeGreaterThan(0)
  })
})
