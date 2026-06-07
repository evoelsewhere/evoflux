import { describe, it, expect } from 'vitest'
import { resolveTemplate, extractReferences } from '../../src/engine/template-resolver'
import { VariablePool } from '../../src/engine/variable-pool'

describe('TemplateResolver', () => {
  it('should resolve single reference', () => {
    const pool = new VariablePool()
    pool.set(['start', 'query'], 'hello world')
    expect(resolveTemplate('{{#start.query#}}', pool)).toBe('hello world')
  })

  it('should resolve multiple references', () => {
    const pool = new VariablePool()
    pool.set(['start', 'query'], 'test')
    pool.set(['llm', 'output'], 'result')
    expect(resolveTemplate('{{#start.query#}} → {{#llm.output#}}', pool)).toBe('test → result')
  })

  it('should resolve missing references to empty string', () => {
    const pool = new VariablePool()
    expect(resolveTemplate('{{#missing.key#}}', pool)).toBe('')
  })

  it('should handle invalid reference format', () => {
    const pool = new VariablePool()
    expect(() => resolveTemplate('{{#invalid#}}', pool)).toThrow()
  })

  it('should leave non-reference text unchanged', () => {
    const pool = new VariablePool()
    expect(resolveTemplate('no references here', pool)).toBe('no references here')
  })

  it('should extract references', () => {
    const refs = extractReferences('{{#a.b#}} and {{#c.d#}} and {{#a.b#}}')
    expect(refs).toEqual([['a', 'b'], ['c', 'd']])
  })

  it('should deduplicate references', () => {
    const refs = extractReferences('{{#a.b#}} {{#a.b#}} {{#a.b#}}')
    expect(refs).toHaveLength(1)
  })
})
