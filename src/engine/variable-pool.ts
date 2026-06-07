export type Selector = [nodeId: string, key: string]

export type SegmentType = 'string' | 'number' | 'boolean' | 'object' | 'array' | 'file' | 'null'

export class Segment {
  readonly type: SegmentType
  readonly value: unknown

  constructor(value: unknown) {
    this.type = Segment.resolveType(value)
    this.value = value
  }

  get text(): string {
    if (this.value === null || this.value === undefined) return ''
    if (typeof this.value === 'object') return JSON.stringify(this.value)
    return String(this.value)
  }

  get number(): number {
    const n = Number(this.value)
    if (isNaN(n)) return 0
    return n
  }

  get bool(): boolean {
    if (typeof this.value === 'boolean') return this.value
    if (typeof this.value === 'string') return this.value === 'true'
    if (typeof this.value === 'number') return this.value !== 0
    return false
  }

  private static resolveType(value: unknown): SegmentType {
    if (value === null || value === undefined) return 'null'
    if (Array.isArray(value)) return 'array'
    const t = typeof value
    if (t === 'function') return 'object'
    return t as SegmentType
  }
}

export class VariablePool {
  private segments = new Map<string, Map<string, Segment>>()

  set(selector: Selector, value: unknown): void {
    const [nodeId, key] = selector
    if (!this.segments.has(nodeId)) {
      this.segments.set(nodeId, new Map())
    }
    this.segments.get(nodeId)!.set(key, new Segment(value))
  }

  get(selector: Selector): unknown {
    const [nodeId, key] = selector
    return this.segments.get(nodeId)?.get(key)?.value
  }

  getSegment(selector: Selector): Segment | undefined {
    const [nodeId, key] = selector
    return this.segments.get(nodeId)?.get(key)
  }

  getByPrefix(prefix: string): Map<string, Segment> {
    return this.segments.get(prefix) || new Map()
  }

  has(selector: Selector): boolean {
    const [nodeId, key] = selector
    return this.segments.get(nodeId)?.has(key) ?? false
  }

  delete(selector: Selector): void {
    const [nodeId, key] = selector
    this.segments.get(nodeId)?.delete(key)
  }

  deleteNode(nodeId: string): void {
    this.segments.delete(nodeId)
  }

  clear(): void {
    this.segments.clear()
  }

  resolve(template: string): string {
    return template.replace(/\{\{#([^#]+)#\}\}/g, (_, ref: string) => {
      const parts = ref.split('.')
      if (parts.length !== 2) return ''
      const value = this.get([parts[0], parts[1]])
      if (value === undefined || value === null) return ''
      if (typeof value === 'object') return JSON.stringify(value)
      return String(value)
    })
  }

  toJSON(): Record<string, Record<string, unknown>> {
    const result: Record<string, Record<string, unknown>> = {}
    for (const [nodeId, keys] of this.segments) {
      result[nodeId] = {}
      for (const [key, segment] of keys) {
        result[nodeId][key] = segment.value
      }
    }
    return result
  }
}
