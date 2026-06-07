import { VariablePool } from './variable-pool'
import { TemplateError } from './errors'

const REF_PATTERN = /\{\{#([^#]+)#\}\}/g

export function resolveTemplate(template: string, pool: VariablePool): string {
  return template.replace(REF_PATTERN, (_, ref: string) => {
    const parts = ref.split('.')
    if (parts.length !== 2) {
      throw new TemplateError(`Invalid variable reference: '{{#${ref}#}}'. Expected format: nodeId.key`)
    }
    const [nodeId, key] = parts
    const value = pool.get([nodeId, key])
    if (value === undefined || value === null) return ''
    if (typeof value === 'object') return JSON.stringify(value, null, 2)
    return String(value)
  })
}

export function resolveValue(value: unknown, pool: VariablePool): unknown {
  if (typeof value === 'string') {
    return resolveTemplate(value, pool)
  }
  if (Array.isArray(value)) {
    return value.map(item => resolveValue(item, pool))
  }
  if (value !== null && typeof value === 'object') {
    if (value instanceof Date || value instanceof RegExp) return value
    if (value instanceof Map || value instanceof Set) return value
    const result: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      result[k] = resolveValue(v, pool)
    }
    return result
  }
  return value
}

export function extractReferences(template: string): Array<[string, string]> {
  const refs: Array<[string, string]> = []
  const seen = new Set<string>()

  let match: RegExpExecArray | null
  const pattern = new RegExp(REF_PATTERN.source, 'g')
  while ((match = pattern.exec(template)) !== null) {
    const ref = match[1]
    const parts = ref.split('.')
    if (parts.length === 2) {
      const key = `${parts[0]}.${parts[1]}`
      if (!seen.has(key)) {
        seen.add(key)
        refs.push([parts[0], parts[1]])
      }
    }
  }

  return refs
}
