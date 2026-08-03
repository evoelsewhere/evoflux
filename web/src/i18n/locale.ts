import { STORAGE_KEYS } from '@/lib/storage-keys'

export const SUPPORTED_LOCALES = ['en', 'vi', 'ja'] as const
export type AppLocale = (typeof SUPPORTED_LOCALES)[number]

export const INTL_LOCALES: Record<AppLocale, string> = {
  en: 'en-US',
  vi: 'vi-VN',
  ja: 'ja-JP',
}

const listeners = new Set<() => void>()
let activeLocale: AppLocale | null = null

export function isAppLocale(value: string | null | undefined): value is AppLocale {
  return SUPPORTED_LOCALES.includes(value as AppLocale)
}

function detectedLocale(): AppLocale {
  if (typeof navigator === 'undefined') return 'en'
  const requested = navigator.languages?.length ? navigator.languages : [navigator.language]
  for (const language of requested) {
    const base = language.toLowerCase().split('-')[0]
    if (isAppLocale(base)) return base
  }
  return 'en'
}

export function readLocale(): AppLocale {
  if (activeLocale) return activeLocale
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(STORAGE_KEYS.locale)
    if (isAppLocale(stored)) {
      activeLocale = stored
      return activeLocale
    }
  }
  activeLocale = detectedLocale()
  return activeLocale
}

function applyDocumentLocale(locale: AppLocale): void {
  if (typeof document === 'undefined') return
  document.documentElement.lang = locale
  document.documentElement.dataset.locale = locale
}

export function initLocale(): AppLocale {
  const locale = readLocale()
  applyDocumentLocale(locale)
  return locale
}

export function getLocale(): AppLocale {
  return readLocale()
}

export function getIntlLocale(locale = getLocale()): string {
  return INTL_LOCALES[locale]
}

export function setLocale(locale: AppLocale): void {
  if (!isAppLocale(locale)) return
  const changed = locale !== readLocale()
  activeLocale = locale
  if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEYS.locale, locale)
  applyDocumentLocale(locale)
  if (changed) listeners.forEach((listener) => listener())
}

export function subscribeLocale(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function resetLocaleForTests(): void {
  activeLocale = null
}
