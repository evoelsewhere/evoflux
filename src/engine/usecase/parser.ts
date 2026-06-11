import { readFile, readdir, stat } from 'fs/promises'
import { join, dirname, basename, extname } from 'path'

export interface UsecaseDefinition {
  name: string
  description: string
  version?: string
  author?: string
  tags?: string[]
  kb_queries: string[]
  context_template: string
  output_format?: string
  tools?: string[]
  max_iterations?: number
  body: string
  source_path: string
  includes: string[]
}

interface ParsedFrontmatter {
  name?: string
  description?: string
  version?: string
  author?: string
  tags?: string[]
  kb_queries?: string[]
  context_template?: string
  output_format?: string
  tools?: string[]
  max_iterations?: number
}

const MAX_INCLUDE_DEPTH = 5
const INCLUDE_PATTERN = /\{include:([^}]+)\}/g
const SECTION_PATTERN = /^(#{1,6})\s+(.+)$/gm

const parsedCache = new Map<string, { hash: string; definition: UsecaseDefinition }>()

function simpleHash(content: string): string {
  let hash = 0
  for (let i = 0; i < content.length; i++) {
    const char = content.charCodeAt(i)
    hash = ((hash << 5) - hash) + char
    hash = hash & hash
  }
  return hash.toString(36)
}

export async function parseUsecaseFile(filePath: string): Promise<UsecaseDefinition> {
  const content = await readFile(filePath, 'utf-8')
  const hash = simpleHash(content)

  const cached = parsedCache.get(filePath)
  if (cached && cached.hash === hash) return cached.definition

  const { frontmatter, body } = parseFrontmatter(content)
  const baseDir = dirname(filePath)

  const resolvedBody = await resolveIncludes(body, baseDir, new Set(), 0)

  const definition: UsecaseDefinition = {
    name: frontmatter.name || basename(filePath, extname(filePath)),
    description: frontmatter.description || '',
    version: frontmatter.version,
    author: frontmatter.author,
    tags: frontmatter.tags || [],
    kb_queries: frontmatter.kb_queries || [],
    context_template: frontmatter.context_template || resolvedBody,
    output_format: frontmatter.output_format,
    tools: frontmatter.tools,
    max_iterations: frontmatter.max_iterations,
    body: resolvedBody,
    source_path: filePath,
    includes: []
  }

  parsedCache.set(filePath, { hash, definition })
  return definition
}

export async function listUsecases(projectPath: string): Promise<Array<{ name: string; description: string; path: string; tags: string[] }>> {
  const usecasesDir = join(projectPath, '.evoflux', 'usecases')
  const results: Array<{ name: string; description: string; path: string; tags: string[] }> = []

  try {
    await scanUsecaseDir(usecasesDir, results)
  } catch { /* .evoflux/usecases doesn't exist */ }

  return results
}

async function scanUsecaseDir(dir: string, results: Array<{ name: string; description: string; path: string; tags: string[] }>): Promise<void> {
  let entries: string[]
  try {
    entries = await readdir(dir)
  } catch { return }

  for (const entry of entries) {
    const fullPath = join(dir, entry)
    const fileStat = await stat(fullPath)

    if (fileStat.isDirectory()) {
      if (entry === 'shared') continue
      await scanUsecaseDir(fullPath, results)
      continue
    }

    if (extname(entry) !== '.md') continue

    try {
      const def = await parseUsecaseFile(fullPath)
      results.push({
        name: def.name,
        description: def.description,
        path: fullPath,
        tags: def.tags || []
      })
    } catch { /* skip invalid files */ }
  }
}

function parseFrontmatter(content: string): { frontmatter: ParsedFrontmatter; body: string } {
  const frontmatter: ParsedFrontmatter = {}
  let body = content

  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/)
  if (match) {
    const yamlStr = match[1]
    body = match[2]

    const lines = yamlStr.split('\n')
    let currentKey = ''
    let currentList: string[] | null = null
    let multilineValue = ''
    let inMultiline = false

    for (const line of lines) {
      if (inMultiline) {
        if (line.match(/^\s{2,}/) || line.trim() === '') {
          multilineValue += line.trimStart() + '\n'
          continue
        } else {
          (frontmatter as any)[currentKey] = multilineValue.trim()
          inMultiline = false
          multilineValue = ''
        }
      }

      const kvMatch = line.match(/^(\w+):\s*(.*)$/)
      if (kvMatch) {
        const key = kvMatch[1]
        let value = kvMatch[2].trim()

        if (value === '|') {
          inMultiline = true
          currentKey = key
          multilineValue = ''
          continue
        }

        if (value.startsWith('[') && value.endsWith(']')) {
          (frontmatter as any)[key] = value.slice(1, -1).split(',').map(s => s.trim().replace(/['"]/g, ''))
          continue
        }

        if (value === '') {
          currentKey = key
          currentList = []
          continue
        }

        ;(frontmatter as any)[key] = value.replace(/^['"]|['"]$/g, '')
        currentKey = key
        currentList = null
        continue
      }

      const listMatch = line.match(/^\s+-\s+(.+)$/)
      if (listMatch && currentKey) {
        if (!currentList) currentList = []
        currentList.push(listMatch[1].trim().replace(/^['"]|['"]$/g, ''))
        ;(frontmatter as any)[currentKey] = currentList
        continue
      }
    }

    if (inMultiline && currentKey) {
      (frontmatter as any)[currentKey] = multilineValue.trim()
    }
  }

  return { frontmatter, body }
}

async function resolveIncludes(
  content: string,
  baseDir: string,
  visited: Set<string>,
  depth: number
): Promise<string> {
  if (depth >= MAX_INCLUDE_DEPTH) {
    return content.replace(INCLUDE_PATTERN, '[ERROR: Max include depth exceeded]')
  }

  const matches = [...content.matchAll(INCLUDE_PATTERN)]
  if (matches.length === 0) return content

  let resolved = content

  for (const match of matches) {
    const fullMatch = match[0]
    const includePath = match[1].trim()

    const [filePath, section] = includePath.split('#')

    if (filePath.includes('*')) {
      const expanded = await resolveGlobInclude(filePath, baseDir, section, visited, depth)
      resolved = resolved.replace(fullMatch, expanded)
      continue
    }

    const fullPath = join(baseDir, filePath)
    const normalizedPath = fullPath

    if (visited.has(normalizedPath)) {
      resolved = resolved.replace(fullMatch, `[ERROR: Circular include: ${filePath}]`)
      continue
    }

    try {
      visited.add(normalizedPath)
      let fileContent = await readFile(fullPath, 'utf-8')

      if (section) {
        fileContent = extractSection(fileContent, section)
      }

      const nestedResolved = await resolveIncludes(fileContent, dirname(fullPath), visited, depth + 1)
      resolved = resolved.replace(fullMatch, nestedResolved)
    } catch {
      resolved = resolved.replace(fullMatch, `[ERROR: File not found: ${filePath}]`)
    }
  }

  return resolved
}

async function resolveGlobInclude(
  pattern: string,
  baseDir: string,
  section: string | undefined,
  visited: Set<string>,
  depth: number
): Promise<string> {
  const dir = dirname(pattern)
  const filePattern = basename(pattern)
  const targetDir = join(baseDir, dir)

  let entries: string[]
  try {
    entries = await readdir(targetDir)
  } catch { return `[ERROR: Directory not found: ${dir}]` }

  const regex = new RegExp('^' + filePattern.replace(/\*/g, '.*').replace(/\?/g, '.') + '$')
  const matchingFiles = entries.filter(e => regex.test(e)).sort()

  const parts: string[] = []
  for (const file of matchingFiles) {
    const fullPath = join(targetDir, file)
    try {
      const fileStat = await stat(fullPath)
      if (!fileStat.isFile()) continue

      const normalizedPath = fullPath
      if (visited.has(normalizedPath)) continue

      visited.add(normalizedPath)
      let content = await readFile(fullPath, 'utf-8')

      if (section) content = extractSection(content, section)

      const nestedResolved = await resolveIncludes(content, dirname(fullPath), visited, depth + 1)
      parts.push(`<!-- ${file} -->\n${nestedResolved}`)
    } catch { /* skip unreadable files */ }
  }

  return parts.join('\n\n')
}

function extractSection(content: string, sectionName: string): string {
  const lines = content.split('\n')
  const sectionLower = sectionName.toLowerCase()
  let inSection = false
  let sectionLevel = 0
  const result: string[] = []

  for (const line of lines) {
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/)

    if (headingMatch) {
      const headingText = headingMatch[2].trim().toLowerCase()

      if (!inSection && headingText === sectionLower) {
        inSection = true
        sectionLevel = headingMatch[1].length
        result.push(line)
        continue
      }

      if (inSection && headingMatch[1].length <= sectionLevel) {
        break
      }
    }

    if (inSection) result.push(line)
  }

  return result.join('\n').trim()
}

export function clearUsecaseCache(): void {
  parsedCache.clear()
}
