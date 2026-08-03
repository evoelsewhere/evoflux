import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

const WEB_ROOT = path.resolve(import.meta.dir, '../..')
const SOURCE_ROOT = path.join(WEB_ROOT, 'src')
const CATALOG_ROOT = path.join(SOURCE_ROOT, 'i18n', 'messages')
const TRANSLATE = process.argv.includes('--translate')

const ATTRIBUTE_NAMES = new Set([
  'alt',
  'aria-description',
  'aria-label',
  'cancelLabel',
  'confirmLabel',
  'description',
  'emptyMessage',
  'hint',
  'label',
  'lede',
  'placeholder',
  'title',
  'tooltip',
])

const PROPERTY_NAMES = new Set([
  ...ATTRIBUTE_NAMES,
  'actionLabel',
  'caption',
  'errorText',
  'message',
  'name',
  'statusText',
  'subtitle',
  'successText',
])

const ENTITY_MAP: Record<string, string> = {
  '&amp;': '&',
  '&apos;': "'",
  '&gt;': '>',
  '&ldquo;': '“',
  '&lsquo;': '‘',
  '&lt;': '<',
  '&nbsp;': ' ',
  '&quot;': '"',
  '&rdquo;': '”',
  '&rsquo;': '’',
}

function decodeEntities(value: string): string {
  return value.replace(/&(?:amp|apos|gt|ldquo|lsquo|lt|nbsp|quot|rdquo|rsquo);/g, (entity) => ENTITY_MAP[entity] ?? entity)
}

function normalize(value: string): string {
  return decodeEntities(value).replace(/\s+/g, ' ').trim()
}

function looksUserFacing(value: string): boolean {
  if (value.length < 2 || !/[A-Za-z]/.test(value)) return false
  if (/^(?:https?:|data:|var\(|--|[.#/]|[a-z]+:\/\/)/.test(value)) return false
  if (/^[\w@./:-]+\.(?:ts|tsx|js|jsx|json|md|py|css|html|svg|png|jpg|jpeg|gif|pdf|docx|xlsx|pptx)$/i.test(value)) return false
  if (/\b(?:bg|text|border|rounded|hover|focus|items|justify|grid|flex|gap|space|px|py|mt|mb|ml|mr|pt|pb|pl|pr|w|h|min|max|shrink|grow|overflow|absolute|relative|fixed|sticky|inset|z|opacity|transition|duration|font|tracking|leading|shadow|ring|outline|translate|scale)-/.test(value)) return false
  if (/^[A-Z0-9_]+$/.test(value) && !value.includes(' ')) return false
  return true
}

function add(catalog: Set<string>, raw: string): void {
  const value = normalize(raw)
  if (looksUserFacing(value)) catalog.add(value)
}

function templateText(node: ts.TemplateExpression): string {
  let value = node.head.text
  node.templateSpans.forEach((span, index) => {
    value += `{${index}}${span.literal.text}`
  })
  return value
}

function hasJsxExpressionAncestor(node: ts.Node): boolean {
  let current: ts.Node | undefined = node.parent
  while (current) {
    if (ts.isJsxExpression(current)) return true
    if (ts.isStatement(current) || ts.isSourceFile(current)) return false
    current = current.parent
  }
  return false
}

function propertyName(node: ts.PropertyName): string | null {
  return ts.isIdentifier(node) || ts.isStringLiteral(node) ? node.text : null
}

function hasUiContainerAncestor(node: ts.Node): boolean {
  let current: ts.Node | undefined = node.parent
  while (current) {
    if (ts.isVariableDeclaration(current) && ts.isIdentifier(current.name)) {
      return /(?:action|choice|copy|empty|item|label|menu|message|option|preset|section|status|tab|text|title)/i.test(current.name.text)
    }
    if (ts.isStatement(current) || ts.isSourceFile(current)) return false
    current = current.parent
  }
  return false
}

function isNativePromptCall(node: ts.CallExpression): boolean {
  const expression = node.expression
  if (ts.isIdentifier(expression)) return ['alert', 'confirm', 'prompt'].includes(expression.text)
  return ts.isPropertyAccessExpression(expression)
    && ts.isIdentifier(expression.expression)
    && expression.expression.text === 'window'
    && ['alert', 'confirm', 'prompt'].includes(expression.name.text)
}

function isTranslationCall(node: ts.CallExpression): boolean {
  return ts.isIdentifier(node.expression) && ['t', 'translate', 'translateText'].includes(node.expression.text)
}

function sourceFiles(): string[] {
  const files: string[] = []
  const walk = (directory: string) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.isDirectory() && ['__tests__', 'assets', 'i18n'].includes(entry.name)) continue
      const absolute = path.join(directory, entry.name)
      if (entry.isDirectory()) walk(absolute)
      else if (/\.(?:ts|tsx)$/.test(entry.name) && !/\.(?:test|spec)\./.test(entry.name)) files.push(absolute)
    }
  }
  walk(SOURCE_ROOT)
  return files.sort()
}

function extractMessages(): string[] {
  const catalog = new Set<string>()
  for (const file of sourceFiles()) {
    const source = fs.readFileSync(file, 'utf8')
    const sourceFile = ts.createSourceFile(
      file,
      source,
      ts.ScriptTarget.Latest,
      true,
      file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    )

    const visit = (node: ts.Node): void => {
      if (ts.isJsxText(node)) add(catalog, node.getText(sourceFile))

      if (ts.isJsxAttribute(node) && ATTRIBUTE_NAMES.has(node.name.text)) {
        const initializer = node.initializer
        if (initializer && ts.isStringLiteral(initializer)) add(catalog, initializer.text)
      }

      if (ts.isPropertyAssignment(node)) {
        const name = propertyName(node.name)
        if (name && PROPERTY_NAMES.has(name)) {
          if (ts.isStringLiteral(node.initializer)) add(catalog, node.initializer.text)
          if (ts.isTemplateExpression(node.initializer)) add(catalog, templateText(node.initializer))
        }
      }

      if (ts.isStringLiteral(node) && hasJsxExpressionAncestor(node)) add(catalog, node.text)
      if (ts.isTemplateExpression(node) && hasJsxExpressionAncestor(node)) add(catalog, templateText(node))
      if (ts.isStringLiteral(node) && hasUiContainerAncestor(node)) add(catalog, node.text)
      if (ts.isTemplateExpression(node)) add(catalog, templateText(node))
      if (ts.isReturnStatement(node) && node.expression && ts.isStringLiteral(node.expression)) add(catalog, node.expression.text)

      if (ts.isCallExpression(node) && isNativePromptCall(node)) {
        const first = node.arguments[0]
        if (first && ts.isStringLiteral(first)) add(catalog, first.text)
        if (first && ts.isTemplateExpression(first)) add(catalog, templateText(first))
      }


      if (ts.isCallExpression(node) && isTranslationCall(node)) {
        const first = node.arguments[0]
        if (first && ts.isStringLiteral(first)) add(catalog, first.text)
        if (first && ts.isTemplateExpression(first)) add(catalog, templateText(first))
      }

      ts.forEachChild(node, visit)
    }
    visit(sourceFile)
  }
  return [...catalog].sort((left, right) => left.localeCompare(right))
}

function readCatalog(locale: string): Record<string, string> {
  const file = path.join(CATALOG_ROOT, `${locale}.json`)
  if (!fs.existsSync(file)) return {}
  return JSON.parse(fs.readFileSync(file, 'utf8')) as Record<string, string>
}

function writeCatalog(locale: string, messages: Record<string, string>): void {
  const ordered = Object.fromEntries(Object.entries(messages).sort(([left], [right]) => left.localeCompare(right)))
  fs.mkdirSync(CATALOG_ROOT, { recursive: true })
  fs.writeFileSync(path.join(CATALOG_ROOT, `${locale}.json`), `${JSON.stringify(ordered, null, 2)}\n`)
}

function translatedText(payload: unknown): string {
  if (!Array.isArray(payload) || !Array.isArray(payload[0])) throw new Error('Unexpected translation response')
  return payload[0].map((row: unknown) => Array.isArray(row) ? String(row[0] ?? '') : '').join('')
}

function batches(messages: string[], maxCharacters = 3_500): string[][] {
  const output: string[][] = []
  let current: string[] = []
  let length = 0
  for (const message of messages) {
    const nextLength = message.length + 24
    if (current.length > 0 && length + nextLength > maxCharacters) {
      output.push(current)
      current = []
      length = 0
    }
    current.push(message)
    length += nextLength
  }
  if (current.length > 0) output.push(current)
  return output
}

async function translateBatch(messages: string[], locale: 'vi' | 'ja'): Promise<string[]> {
  const markers = messages.slice(1).map((_, index) => `__I18N_${String(index + 1).padStart(4, '0')}__`)
  const query = messages.flatMap((message, index) => index === 0 ? [message] : [markers[index - 1], message]).join('\n')
  const params = new URLSearchParams({ client: 'gtx', sl: 'en', tl: locale, dt: 't', q: query })
  const response = await fetch(`https://translate.googleapis.com/translate_a/single?${params}`)
  if (!response.ok) throw new Error(`Translation request failed (${response.status})`)
  const translated = translatedText(await response.json())
  const markerPattern = new RegExp(`\\n?(?:${markers.join('|')})\\n?`, 'g')
  const parts = translated.split(markerPattern).map((part) => part.trim())
  if (parts.length !== messages.length) {
    throw new Error(`Translation batch split mismatch: expected ${messages.length}, received ${parts.length}`)
  }
  return parts
}

async function translateMissing(messages: string[], locale: 'vi' | 'ja'): Promise<Record<string, string>> {
  const existing = readCatalog(locale)
  const missing = messages.filter((message) => !existing[message])
  const groups = batches(missing)
  for (let index = 0; index < groups.length; index += 1) {
    const group = groups[index]
    process.stdout.write(`\r${locale}: translating batch ${index + 1}/${groups.length}`)
    const translations = await translateBatch(group, locale)
    group.forEach((message, messageIndex) => {
      existing[message] = translations[messageIndex] || message
    })
  }
  if (groups.length > 0) process.stdout.write('\n')
  const placeholders = (value: string) => [...value.matchAll(/\{\d+\}/g)].map((match) => match[0]).sort().join('|')
  return Object.fromEntries(messages.map((message) => {
    const candidate = existing[message] ?? message
    return [message, placeholders(candidate) === placeholders(message) ? candidate : message]
  }))
}

const messages = extractMessages()
writeCatalog('en', Object.fromEntries(messages.map((message) => [message, message])))

if (TRANSLATE) {
  writeCatalog('vi', await translateMissing(messages, 'vi'))
  writeCatalog('ja', await translateMissing(messages, 'ja'))
} else {
  for (const locale of ['vi', 'ja'] as const) {
    const existing = readCatalog(locale)
    writeCatalog(locale, Object.fromEntries(messages.map((message) => [message, existing[message] ?? message])))
  }
}

console.log(`Extracted ${messages.length} messages into ${path.relative(WEB_ROOT, CATALOG_ROOT)}`)
