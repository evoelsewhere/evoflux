import { parseUsecaseFile, listUsecases, type UsecaseDefinition } from './parser'
import { hybridSearch } from '../kb/hybrid-search'
import { join, dirname } from 'path'
import { readFile } from 'fs/promises'

export interface UsecaseExecutionResult {
  usecase: UsecaseDefinition
  context: string
  kb_results: Record<string, string[]>
  tools: string[]
  max_iterations: number
}

export async function executeUsecase(
  projectPath: string,
  usecaseName: string,
  kbId: string,
  input: string,
  options?: {
    aiChat?: (messages: Array<{ role: string; content: string }>, opts?: { model?: string; provider?: string }) => Promise<string>
    model?: string
    provider?: string
    maxResults?: number
  }
): Promise<UsecaseExecutionResult> {
  const usecases = await listUsecases(projectPath)
  const usecasePath = usecases.find(u => u.name === usecaseName)?.path

  if (!usecasePath) {
    throw new Error(`Usecase "${usecaseName}" not found in ${join(projectPath, '.evoflux', 'usecases')}`)
  }

  const definition = await parseUsecaseFile(usecasePath)

  const kbResults: Record<string, string[]> = {}

  for (let i = 0; i < definition.kb_queries.length; i++) {
    const query = definition.kb_queries[i]
    try {
      const results = await hybridSearch(kbId, query, { limit: options?.maxResults || 5 })
      kbResults[`kb_result_${i}`] = results.map(r => {
        const meta = r.metadata_json ? JSON.parse(r.metadata_json) : {}
        const heading = meta.heading ? `[${meta.heading}] ` : ''
        return `**${r.doc_name}** ${heading}(score: ${r.hybrid_score.toFixed(2)})\n${r.content.substring(0, 500)}`
      })
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error)
      kbResults[`kb_result_${i}`] = [`[Search failed for "${query}": ${msg}]`]
    }
  }

  if (Object.values(kbResults).every(r => r.length === 0)) {
    kbResults['warning'] = ['No KB query results. The KB may be empty or queries returned no matches.']
  }

  let context = definition.context_template || definition.body

  context = context.replace(/\{input\}/g, input || '')
  context = context.replace(/\{project_path\}/g, projectPath)
  context = context.replace(/\{usecase_name\}/g, definition.name)

  const functionCode = input || ''
  const functionMap: Record<string, string> = {
    INV: 'Invoice', CUS: 'Customer', PRD: 'Product', EIN: 'EInvoice',
    PAY: 'Payment', RPT: 'Report', USR: 'User', INT: 'Integration',
    SEC: 'Security', SET: 'Settings'
  }
  const modulePrefix = functionCode.replace(/_\d+$/, '')
  const functionName = functionMap[modulePrefix] || modulePrefix || functionCode
  context = context.replace(/\{function_code\}/g, functionCode)
  context = context.replace(/\{function_name\}/g, functionName)
  context = context.replace(/\{module\}/g, functionName)

  for (const [key, values] of Object.entries(kbResults)) {
    context = context.replace(new RegExp(`\\{${key}\\}`, 'g'), values.join('\n\n'))
  }

  const allResults = Object.values(kbResults).flat()
  context = context.replace(/\{kb_results_all\}/g, allResults.join('\n\n'))

  const usecaseDir = dirname(usecasePath)
  const includePattern = /\{include:([^}]+)\}/g
  let includeMatch: RegExpExecArray | null
  while ((includeMatch = includePattern.exec(context)) !== null) {
    const includePath = includeMatch[1].trim()
    try {
      const fullPath = join(usecaseDir, includePath)
      const fileContent = await readFile(fullPath, 'utf-8')
      context = context.replace(includeMatch[0], fileContent)
    } catch {
      context = context.replace(includeMatch[0], `[ERROR: File not found: ${includePath}]`)
    }
  }

  return {
    usecase: definition,
    context,
    kb_results: kbResults,
    tools: definition.tools || [],
    max_iterations: definition.max_iterations || 20
  }
}
