const MODEL = 'Xenova/multilingual-e5-small'
const DIMENSION = 384

type EmbedderFn = (input: string, options: { pooling: string; normalize: boolean }) => Promise<{ data: Float32Array }>

let embedder: EmbedderFn | null = null

function createFallbackEmbedder(): EmbedderFn {
  console.warn('[Embedding] @xenova/transformers not available. Using hash-based deterministic fallback (not suitable for production).')
  return async (input: string) => {
    // Deterministic hash-based pseudo-embedding — same input always produces same vector
    const arr = new Float32Array(DIMENSION)
    let hash = 0
    for (let i = 0; i < input.length; i++) {
      hash = ((hash << 5) - hash + input.charCodeAt(i)) | 0
    }
    for (let i = 0; i < DIMENSION; i++) {
      hash = ((hash << 5) - hash + i) | 0
      arr[i] = (hash % 1000) / 1000
    }
    let norm = 0
    for (let i = 0; i < DIMENSION; i++) norm += arr[i] * arr[i]
    norm = Math.sqrt(norm)
    if (norm > 0) {
      for (let i = 0; i < DIMENSION; i++) arr[i] /= norm
    }
    return { data: arr }
  }
}

async function getEmbedder(): Promise<EmbedderFn> {
  if (!embedder) {
    try {
      const mod = require('@xenova/transformers')
      const pipelineFn = mod.pipeline as (task: string, model: string) => Promise<unknown>
      embedder = (await pipelineFn('feature-extraction', MODEL)) as EmbedderFn
    } catch {
      embedder = createFallbackEmbedder()
    }
  }
  return embedder
}

export async function embed(text: string, mode: 'query' | 'passage' = 'passage'): Promise<Float32Array> {
  const pipe = await getEmbedder()
  const input = mode === 'query' ? `query: ${text}` : `passage: ${text}`
  const output = await pipe(input, { pooling: 'mean', normalize: true })
  return output.data
}

export async function embedBatch(texts: string[], mode: 'query' | 'passage' = 'passage', onProgress?: (current: number, total: number) => void): Promise<Float32Array[]> {
  const pipe = await getEmbedder()
  const results: Float32Array[] = []

  for (let i = 0; i < texts.length; i++) {
    const input = mode === 'query' ? `query: ${texts[i]}` : `passage: ${texts[i]}`
    const output = await pipe(input, { pooling: 'mean', normalize: true })
    results.push(output.data)
    if (onProgress && (i + 1) % 10 === 0) onProgress(i + 1, texts.length)
  }

  onProgress?.(texts.length, texts.length)
  return results
}

export function cosineSimilarity(a: Float32Array, b: Float32Array): number {
  let dot = 0
  let normA = 0
  let normB = 0
  const len = Math.min(a.length, b.length)
  for (let i = 0; i < len; i++) {
    dot += a[i] * b[i]
    normA += a[i] * a[i]
    normB += b[i] * b[i]
  }
  const denom = Math.sqrt(normA) * Math.sqrt(normB)
  return denom === 0 ? 0 : dot / denom
}

export function vectorToBuffer(vec: Float32Array): Buffer {
  return Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength)
}

export function bufferToVector(buf: Buffer): Float32Array {
  return new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4)
}

export const EMBEDDING_DIMENSION = DIMENSION
