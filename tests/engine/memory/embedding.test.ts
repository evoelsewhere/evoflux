import { describe, it, expect } from 'vitest'
import { cosineSimilarity, EMBEDDING_DIMENSION } from '../../../src/engine/memory/embedding'

describe('Embedding', () => {
  it('should have correct dimension', () => {
    expect(EMBEDDING_DIMENSION).toBe(384)
  })

  it('should compute cosine similarity of identical vectors', () => {
    const a = new Float32Array([1, 0, 0])
    const b = new Float32Array([1, 0, 0])
    expect(cosineSimilarity(a, b)).toBeCloseTo(1.0)
  })

  it('should compute cosine similarity of orthogonal vectors', () => {
    const a = new Float32Array([1, 0, 0])
    const b = new Float32Array([0, 1, 0])
    expect(cosineSimilarity(a, b)).toBeCloseTo(0.0)
  })

  it('should compute cosine similarity of opposite vectors', () => {
    const a = new Float32Array([1, 0, 0])
    const b = new Float32Array([-1, 0, 0])
    expect(cosineSimilarity(a, b)).toBeCloseTo(-1.0)
  })

  it('should handle zero vectors', () => {
    const a = new Float32Array([0, 0, 0])
    const b = new Float32Array([1, 0, 0])
    expect(cosineSimilarity(a, b)).toBe(0)
  })
})
