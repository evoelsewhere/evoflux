import en from './messages/en.json'
import ja from './messages/ja.json'
import vi from './messages/vi.json'
import { getLocale, type AppLocale } from './locale'
import { JA_OVERRIDES, VI_OVERRIDES } from './overrides'

type Catalog = Record<string, string>

const catalogs: Record<AppLocale, Catalog> = {
  en,
  vi: { ...vi, ...VI_OVERRIDES },
  ja: { ...ja, ...JA_OVERRIDES },
}
const PLACEHOLDER = /\{(\d+)\}/g

interface MessagePattern {
  key: string
  regex: RegExp
  staticLength: number
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const patterns: MessagePattern[] = Object.keys(en)
  .filter((key) => /\{\d+\}/.test(key) && key.replace(PLACEHOLDER, '').trim().length >= 2)
  .map((key) => {
    PLACEHOLDER.lastIndex = 0
    let cursor = 0
    let expression = '^'
    let match: RegExpExecArray | null
    while ((match = PLACEHOLDER.exec(key))) {
      expression += escapeRegex(key.slice(cursor, match.index))
      expression += '(.*?)'
      cursor = match.index + match[0].length
    }
    expression += `${escapeRegex(key.slice(cursor))}$`
    return { key, regex: new RegExp(expression, 'u'), staticLength: key.replace(PLACEHOLDER, '').length }
  })
  .sort((left, right) => right.staticLength - left.staticLength)

export function translate(key: string, values: ReadonlyArray<string | number> = [], locale = getLocale()): string {
  const translated = catalogs[locale][key] ?? key
  return translated.replace(PLACEHOLDER, (_, index: string) => String(values[Number(index)] ?? `{${index}}`))
}

/**
 * Pattern captures are interpolated verbatim, so a captured span that is itself
 * UI vocabulary would survive untranslated inside a translated frame. Strings
 * composed at runtime hit that path constantly — `"Collapse Projects section"`
 * matches `"{0} {1} section"` and used to render as `"phần Collapse Projects"`.
 * Give every capture an exact catalog lookup first; opaque data (ids, counts,
 * names, paths) has no entry and passes through untouched.
 */
function localizeCapture(capture: string, locale: AppLocale): string {
  const value = capture.trim()
  if (!value) return capture
  const translated = catalogs[locale][value]
  if (!translated || translated === value) return capture
  return capture.replace(value, () => translated)
}

function translateTrimmed(source: string, locale: AppLocale): string {
  const exact = catalogs[locale][source]
  if (exact) return exact

  for (const pattern of patterns) {
    const match = pattern.regex.exec(source)
    if (!match) continue
    const values = match.slice(1).map((capture) => localizeCapture(capture, locale))
    return translate(pattern.key, values, locale)
  }
  return source
}

export function translateText(source: string, locale = getLocale()): string {
  if (!source || locale === 'en') return source
  const leading = source.match(/^\s*/u)?.[0] ?? ''
  const trailing = source.match(/\s*$/u)?.[0] ?? ''
  const end = Math.max(leading.length, source.length - trailing.length)
  const body = source.slice(leading.length, end)
  if (!body) return source
  return `${leading}${translateTrimmed(body, locale)}${trailing}`
}

export function hasTranslation(source: string, locale = getLocale()): boolean {
  return translateText(source, locale) !== source
}
