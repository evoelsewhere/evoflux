import { createHash } from 'crypto'
import { readFile } from 'fs/promises'
import { scanDirectory, scanFiles, type ScannedFile } from './file-scanner'
import { semanticChunk, type Chunk } from './chunker'
import { convertFile } from '../file-reader/markitdown'
import { embedBatch } from '../memory/embedding'
import {
  addDocument, updateDocument, addChunks, removeChunksByDoc,
  addSource, updateSource, listDocuments, removeDocument,
  updateKBStats, getDocument, type ChunkInsert
} from '../db/kb-repo'

export interface PipelineOptions {
  chunkSize?: number
  chunkOverlap?: number
  strategy?: 'auto' | 'heading' | 'paragraph' | 'character' | 'code'
  excludePatterns?: string[]
  maxFileSize?: number
}

export interface PipelineProgress {
  type: 'start' | 'file' | 'complete' | 'error'
  sourceId?: string
  fileName?: string
  fileIndex?: number
  totalFiles?: number
  status?: string
  error?: string
  docsIndexed?: number
  chunksCreated?: number
}

const DEFAULT_MAX_FILE_SIZE = 1024 * 1024

export async function indexFolder(
  kbId: string,
  folderPath: string,
  options?: PipelineOptions,
  onProgress?: (progress: PipelineProgress) => void
): Promise<{ sourceId: string; docsIndexed: number; chunksCreated: number }> {
  const source = addSource(kbId, folderPath, 'folder')
  updateSource(source.id, { status: 'indexing' })
  onProgress?.({ type: 'start', sourceId: source.id })

  try {
    const files = await scanDirectory(folderPath, {
      excludePatterns: options?.excludePatterns,
      maxFiles: 10000
    })

    updateSource(source.id, { file_count: files.length })

    let docsIndexed = 0
    let chunksCreated = 0

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      onProgress?.({ type: 'file', sourceId: source.id, fileName: file.name, fileIndex: i, totalFiles: files.length })

      try {
        const result = await indexFile(kbId, source.id, file, options)
        if (result) {
          docsIndexed++
          chunksCreated += result.chunksCreated
        }
      } catch (error) {
        onProgress?.({ type: 'error', fileName: file.name, error: error instanceof Error ? error.message : String(error) })
      }
    }

    updateSource(source.id, { status: 'indexed' })
    updateKBStats(kbId)
    onProgress?.({ type: 'complete', sourceId: source.id, docsIndexed, chunksCreated })

    return { sourceId: source.id, docsIndexed, chunksCreated }
  } catch (error) {
    updateSource(source.id, { status: 'error', error: error instanceof Error ? error.message : String(error) })
    throw error
  }
}

export async function indexFiles(
  kbId: string,
  filePaths: string[],
  options?: PipelineOptions,
  onProgress?: (progress: PipelineProgress) => void
): Promise<{ sourceId: string; docsIndexed: number; chunksCreated: number }> {
  const source = addSource(kbId, filePaths[0] || 'uploaded-files', 'file')
  updateSource(source.id, { status: 'indexing' })
  onProgress?.({ type: 'start', sourceId: source.id })

  try {
    const files = await scanFiles(filePaths)
    updateSource(source.id, { file_count: files.length })

    let docsIndexed = 0
    let chunksCreated = 0

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      onProgress?.({ type: 'file', sourceId: source.id, fileName: file.name, fileIndex: i, totalFiles: files.length })

      try {
        const result = await indexFile(kbId, source.id, file, options)
        if (result) {
          docsIndexed++
          chunksCreated += result.chunksCreated
        }
      } catch (error) {
        onProgress?.({ type: 'error', fileName: file.name, error: error instanceof Error ? error.message : String(error) })
      }
    }

    updateSource(source.id, { status: 'indexed' })
    updateKBStats(kbId)
    onProgress?.({ type: 'complete', sourceId: source.id, docsIndexed, chunksCreated })

    return { sourceId: source.id, docsIndexed, chunksCreated }
  } catch (error) {
    updateSource(source.id, { status: 'error', error: error instanceof Error ? error.message : String(error) })
    throw error
  }
}

async function indexFile(
  kbId: string,
  sourceId: string,
  file: ScannedFile,
  options?: PipelineOptions
): Promise<{ docId: string; chunksCreated: number } | null> {
  const maxSize = options?.maxFileSize ?? DEFAULT_MAX_FILE_SIZE
  if (file.size > maxSize) return null

  const contentHash = await hashFile(file.path)
  const existingDoc = findDocByPath(kbId, file.path)
  if (existingDoc && existingDoc.indexed_content_hash === contentHash) {
    return null
  }

  const doc = addDocument(kbId, sourceId, file.path, file.name, file.extension, file.size)
  updateDocument(doc.id, { status: 'processing' })

  try {
    const content = await extractText(file)
    if (!content || content.trim().length === 0) {
      updateDocument(doc.id, { status: 'indexed', content_preview: '', chunk_count: 0, indexed_content_hash: contentHash })
      return { docId: doc.id, chunksCreated: 0 }
    }

    const chunks = semanticChunk(content, file.path, {
      chunkSize: options?.chunkSize,
      chunkOverlap: options?.chunkOverlap,
      strategy: options?.strategy
    })

    if (chunks.length === 0) {
      updateDocument(doc.id, { status: 'indexed', content_preview: content.substring(0, 500), chunk_count: 0, indexed_content_hash: contentHash })
      return { docId: doc.id, chunksCreated: 0 }
    }

    const texts = chunks.map(c => c.content)
    const embeddings = await embedBatch(texts, 'passage')

    const chunkInserts: ChunkInsert[] = chunks.map((c, i) => ({
      content: c.content,
      embedding: Array.from(embeddings[i]),
      metadata: c.metadata as unknown as Record<string, unknown>
    }))

    if (existingDoc) {
      removeChunksByDoc(existingDoc.id)
      removeDocument(existingDoc.id)
    }

    addChunks(doc.id, kbId, chunkInserts)

    const preview = content.substring(0, 500)
    updateDocument(doc.id, {
      status: 'indexed',
      content_preview: preview,
      chunk_count: chunks.length,
      indexed_content_hash: contentHash
    })

    return { docId: doc.id, chunksCreated: chunks.length }
  } catch (error) {
    updateDocument(doc.id, { status: 'error', error: error instanceof Error ? error.message : String(error) })
    throw error
  }
}

async function extractText(file: ScannedFile): Promise<string> {
  if (file.parser === 'markitdown') {
    const result = await convertFile(file.path, { useMarkitdown: true })
    return result.content
  }

  try {
    return await readFile(file.path, 'utf-8')
  } catch {
    return ''
  }
}

async function hashFile(filePath: string): Promise<string> {
  const content = await readFile(filePath)
  return createHash('md5').update(content).digest('hex')
}

function findDocByPath(kbId: string, path: string) {
  const docs = listDocuments(kbId)
  return docs.find(d => d.path === path)
}
