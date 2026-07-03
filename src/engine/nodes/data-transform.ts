import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface DataTransformConfig {
  data?: unknown
  operations?: Array<{
    type: 'extract' | 'map' | 'filter' | 'merge' | 'keys' | 'values' | 'length' | 'flatten' | 'unique' | 'sort' | 'slice' | 'stringify' | 'parse'
    path?: string
    expression?: string
    field?: string
    value?: unknown
    source?: unknown
    start?: number
    end?: number
  }>
}

export class DataTransformNode extends BaseNode<DataTransformConfig> {
  readonly type = 'data-transform'

  getMetadata(): NodeMetadata {
    return {
      type: 'data-transform',
      label: 'Data Transform',
      icon: 'swap',
      category: 'logic',
      description: 'Transform data: extract by path, map/filter arrays, merge objects, sort, flatten, unique.',
      inputs: [
        { name: 'data', label: 'Input Data', type: 'object', required: true }
      ],
      outputs: [
        { name: 'output', label: 'Result', type: 'object', required: false },
        { name: 'type', label: 'Result Type', type: 'string', required: false }
      ],
      defaultConfig: { operations: [{ type: 'extract', path: '' }] }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as DataTransformConfig
    let data: unknown = inputs.data ?? cfg.data

    const operations = cfg.operations || []

    try {
      for (const op of operations) {
        data = applyTransform(data, op)
      }

      return {
        output: data,
        type: Array.isArray(data) ? 'array' : data === null ? 'null' : typeof data
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Transform failed'
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error })
    }
  }
}

function applyTransform(data: unknown, op: DataTransformConfig['operations'] extends (infer U)[] | undefined ? U : never): unknown {
  switch (op.type) {
    case 'extract':
      return extractPath(data, op.path || '')

    case 'map': {
      if (!Array.isArray(data)) throw new Error('map requires array input')
      const field = op.field || op.expression || ''
      return data.map(item => extractPath(item, field))
    }

    case 'filter': {
      if (!Array.isArray(data)) throw new Error('filter requires array input')
      const field = op.field || ''
      const value = op.value
      if (!field) return data
      return data.filter(item => {
        const itemValue = extractPath(item, field)
        if (value === undefined) return itemValue !== undefined && itemValue !== null && itemValue !== ''
        return String(itemValue) === String(value)
      })
    }

    case 'merge': {
      const source = op.source || {}
      if (typeof data === 'object' && data !== null && typeof source === 'object' && source !== null) {
        return { ...(data as Record<string, unknown>), ...(source as Record<string, unknown>) }
      }
      throw new Error('merge requires object inputs')
    }

    case 'keys': {
      if (typeof data === 'object' && data !== null) return Object.keys(data as Record<string, unknown>)
      throw new Error('keys requires object input')
    }

    case 'values': {
      if (typeof data === 'object' && data !== null) return Object.values(data as Record<string, unknown>)
      throw new Error('values requires object input')
    }

    case 'length': {
      if (Array.isArray(data) || typeof data === 'string') return data.length
      if (typeof data === 'object' && data !== null) return Object.keys(data as Record<string, unknown>).length
      return 0
    }

    case 'flatten': {
      if (!Array.isArray(data)) throw new Error('flatten requires array input')
      return data.flat(Infinity)
    }

    case 'unique': {
      if (!Array.isArray(data)) throw new Error('unique requires array input')
      const field = op.field || ''
      if (field) {
        const seen = new Set()
        return data.filter(item => {
          const val = String(extractPath(item, field))
          if (seen.has(val)) return false
          seen.add(val)
          return true
        })
      }
      return [...new Set(data)]
    }

    case 'sort': {
      if (!Array.isArray(data)) throw new Error('sort requires array input')
      const field = op.field || ''
      const sorted = [...data]
      if (field) {
        sorted.sort((a, b) => {
          const va = String(extractPath(a, field) ?? '')
          const vb = String(extractPath(b, field) ?? '')
          if (va < vb) return -1
          if (va > vb) return 1
          return 0
        })
      } else {
        sorted.sort()
      }
      return sorted
    }

    case 'slice': {
      if (!Array.isArray(data) && typeof data !== 'string') throw new Error('slice requires array or string input')
      const start = op.start || 0
      const end = op.end
      return end !== undefined ? data.slice(start, end) : data.slice(start)
    }

    case 'stringify':
      return JSON.stringify(data, null, 2)

    case 'parse': {
      if (typeof data !== 'string') throw new Error('parse requires string input')
      return JSON.parse(data)
    }

    default:
      return data
  }
}

function extractPath(obj: unknown, path: string): unknown {
  if (!path) return obj
  const parts = path.split(/[.[\]]/).filter(Boolean)
  let current: unknown = obj

  for (const part of parts) {
    if (current === null || current === undefined) return undefined
    if (typeof current !== 'object') return undefined
    current = (current as Record<string, unknown>)[part]
  }

  return current
}
