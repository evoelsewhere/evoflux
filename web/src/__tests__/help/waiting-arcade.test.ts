import { describe, expect, it } from 'vitest'
import { searchHelpArticles, getHelpArticles } from '@/help'
import en from '@/i18n/messages/en.json'
import vi from '@/i18n/messages/vi.json'
import ja from '@/i18n/messages/ja.json'

const requiredMessages = [
  'Play while waiting',
  '2048 game',
  '2048 board',
  'Waiting Arcade',
  'A small local game while your agent works.',
  'Close game',
  'Choose another game',
  'Start Snake',
  'Start Minesweeper',
  'Start Tic-tac-toe',
  'New game',
  'Snake board',
  'Minesweeper board',
  'Tic-tac-toe board',
  'Cell {0}, {1} hidden',
  'Cell {0}, {1} flagged',
  'Cell {0}, {1} revealed{2}',
  'Cell {0}: {1}',
  'Use arrow keys to move, then Enter or Space to reveal or flag.',
  'Use arrow keys to move between cells, then press Enter or Space to play.',
  'Move {0}, score {1}',
  'Tile {0} at row {1}, column {2}',
  'Reduced motion: Snake moves every 480 ms',
]

describe('Waiting Arcade localization and Help', () => {
  it('has matching English, Vietnamese, and Japanese UI messages', () => {
    expect(Object.keys(vi)).toEqual(Object.keys(en))
    expect(Object.keys(ja)).toEqual(Object.keys(en))
    for (const key of requiredMessages) {
      expect(en).toHaveProperty(key)
      expect(vi).toHaveProperty(key)
      expect(ja).toHaveProperty(key)
    }
  })

  it.each(['en', 'vi', 'ja'] as const)('makes the Help article searchable in %s', (locale) => {
    const articles = getHelpArticles(locale)
    expect(articles.some((article) => article.id === 'waiting-arcade')).toBe(true)
    expect(searchHelpArticles(articles, 'snake').some((hit) => hit.article.id === 'waiting-arcade')).toBe(true)
    expect(searchHelpArticles(articles, '2048').some((hit) => hit.article.id === 'waiting-arcade')).toBe(true)
  })
})
