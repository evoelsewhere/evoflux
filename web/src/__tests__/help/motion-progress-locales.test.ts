import { describe, it } from 'vitest'
import { HELP_ARTICLES_EN } from '@/help/locales/en'
import { HELP_ARTICLES_VI } from '@/help/locales/vi'
import { HELP_ARTICLES_JA } from '@/help/locales/ja'

function helpText(articles: unknown): string {
  return JSON.stringify(articles)
}

function expectPhrases(text: string, phrases: string[]) {
  for (const phrase of phrases) {
    if (!text.includes(phrase)) throw new Error(`Help translation is missing: ${phrase}`)
  }
}

describe('motion progress help translations', () => {
  it('documents progress, Workbench review, vision fallback, soundtrack status, and legacy recording in English', () => {
    const text = helpText(HELP_ARTICLES_EN)
    expectPhrases(text, [
      'per-frame progress',
      'representative frame previews',
      'active provider accepts images',
      'soundtrack is included or unavailable',
      'real-time browser recording',
    ])
  })

  it('documents the same motion contract in Vietnamese', () => {
    const text = helpText(HELP_ARTICLES_VI)
    expectPhrases(text, [
      'tiến độ từng frame',
      'frame đại diện',
      'timeline Workbench',
      'model hỗ trợ vision',
      'soundtrack đã ghép',
      'không dựng được âm thanh',
      'ghi video thời gian thực',
    ])
  })

  it('documents the same motion contract in Japanese', () => {
    const text = helpText(HELP_ARTICLES_JA)
    expectPhrases(text, [
      'フレームごとの進捗',
      '代表フレーム',
      'Workbench のタイムライン',
      '画像入力に対応する場合',
      'サウンドトラックを含む',
      '音声を生成できなかった',
      'リアルタイム録画',
    ])
  })
})
