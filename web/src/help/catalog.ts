import type { AppLocale } from '@/i18n'

import { HELP_ARTICLES_EN, HELP_CATEGORIES_EN } from './locales/en'
import { HELP_ARTICLES_JA, HELP_CATEGORIES_JA } from './locales/ja'
import { HELP_ARTICLES_VI, HELP_CATEGORIES_VI } from './locales/vi'
import type { HelpArticle, HelpCategory } from './types'

const CATEGORIES: Record<AppLocale, HelpCategory[]> = {
  en: HELP_CATEGORIES_EN,
  vi: HELP_CATEGORIES_VI,
  ja: HELP_CATEGORIES_JA,
}

const ARTICLES: Record<AppLocale, HelpArticle[]> = {
  en: HELP_ARTICLES_EN,
  vi: HELP_ARTICLES_VI,
  ja: HELP_ARTICLES_JA,
}

/** @deprecated Prefer getHelpCategories(locale) — kept for tests that pin English. */
export const HELP_CATEGORIES = HELP_CATEGORIES_EN

/** @deprecated Prefer getHelpArticles(locale) — kept for tests that pin English. */
export const HELP_ARTICLES = HELP_ARTICLES_EN

export function getHelpCategories(locale: AppLocale = 'en'): HelpCategory[] {
  return CATEGORIES[locale] ?? HELP_CATEGORIES_EN
}

export function getHelpArticles(locale: AppLocale = 'en'): HelpArticle[] {
  return ARTICLES[locale] ?? HELP_ARTICLES_EN
}

export function getHelpArticle(
  id: string,
  locale: AppLocale = 'en',
): HelpArticle | undefined {
  return getHelpArticles(locale).find((article) => article.id === id)
}

export function getHelpCategory(
  id: string,
  locale: AppLocale = 'en',
): HelpCategory | undefined {
  return getHelpCategories(locale).find((category) => category.id === id)
}
