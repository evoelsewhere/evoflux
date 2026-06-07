import { describe, it, expect } from 'vitest'
import { VariablePool, Segment } from '../../src/engine/variable-pool'

describe('Segment', () => {
  it('should resolve string type', () => {
    const seg = new Segment('hello')
    expect(seg.type).toBe('string')
    expect(seg.text).toBe('hello')
  })

  it('should resolve number type', () => {
    const seg = new Segment(42)
    expect(seg.type).toBe('number')
    expect(seg.number).toBe(42)
  })

  it('should resolve boolean type', () => {
    const seg = new Segment(true)
    expect(seg.type).toBe('boolean')
    expect(seg.bool).toBe(true)
  })

  it('should resolve array type', () => {
    const seg = new Segment([1, 2, 3])
    expect(seg.type).toBe('array')
  })

  it('should resolve object type', () => {
    const seg = new Segment({ a: 1 })
    expect(seg.type).toBe('object')
    expect(seg.text).toBe('{"a":1}')
  })

  it('should handle null', () => {
    const seg = new Segment(null)
    expect(seg.type).toBe('null')
    expect(seg.text).toBe('')
  })
})

describe('VariablePool', () => {
  it('should set and get variable by selector', () => {
    const pool = new VariablePool()
    pool.set(['node1', 'output'], 'hello')
    expect(pool.get(['node1', 'output'])).toBe('hello')
  })

  it('should return undefined for missing variables', () => {
    const pool = new VariablePool()
    expect(pool.get(['nonexistent', 'key'])).toBeUndefined()
  })

  it('should check if variable exists', () => {
    const pool = new VariablePool()
    pool.set(['node1', 'key'], 'value')
    expect(pool.has(['node1', 'key'])).toBe(true)
    expect(pool.has(['node1', 'missing'])).toBe(false)
  })

  it('should delete variable', () => {
    const pool = new VariablePool()
    pool.set(['node1', 'key'], 'value')
    pool.delete(['node1', 'key'])
    expect(pool.has(['node1', 'key'])).toBe(false)
  })

  it('should delete all node variables', () => {
    const pool = new VariablePool()
    pool.set(['node1', 'a'], 1)
    pool.set(['node1', 'b'], 2)
    pool.set(['node2', 'a'], 3)
    pool.deleteNode('node1')
    expect(pool.has(['node1', 'a'])).toBe(false)
    expect(pool.has(['node2', 'a'])).toBe(true)
  })

  it('should resolve template references', () => {
    const pool = new VariablePool()
    pool.set(['start', 'query'], 'test query')
    pool.set(['llm', 'output'], 'test output')
    const result = pool.resolve('Process: {{#start.query#}} → {{#llm.output#}}')
    expect(result).toBe('Process: test query → test output')
  })

  it('should resolve missing references to empty string', () => {
    const pool = new VariablePool()
    const result = pool.resolve('Value: {{#missing.key#}}')
    expect(result).toBe('Value: ')
  })

  it('should get segment', () => {
    const pool = new VariablePool()
    pool.set(['node1', 'output'], 42)
    const seg = pool.getSegment(['node1', 'output'])
    expect(seg).toBeInstanceOf(Segment)
    expect(seg?.number).toBe(42)
  })

  it('should get by prefix', () => {
    const pool = new VariablePool()
    pool.set(['node1', 'a'], 1)
    pool.set(['node1', 'b'], 2)
    pool.set(['node2', 'a'], 3)
    const node1Vars = pool.getByPrefix('node1')
    expect(node1Vars.size).toBe(2)
  })

  it('should serialize to JSON', () => {
    const pool = new VariablePool()
    pool.set(['node1', 'a'], 1)
    pool.set(['node2', 'b'], 'hello')
    const json = pool.toJSON()
    expect(json).toEqual({ node1: { a: 1 }, node2: { b: 'hello' } })
  })
})
