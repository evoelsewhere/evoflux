import { createHash } from 'crypto'
import { readFile } from 'fs/promises'
import { join } from 'path'
import { scanDirectory, scanFiles, type ScannedFile } from './file-scanner'
import { semanticChunk, type Chunk } from './chunker'
import { convertFile } from '../file-reader/markitdown'
import { embedBatch } from '../memory/embedding'
import { detectGitRepo, getChangedFiles, getCurrentCommit, getCurrentBranch, getContentHash } from './git-ops'
import {
  addDocument, updateDocument, addChunks, removeChunksByDoc,
  addSource, updateSource, listDocuments, removeDocument,
  updateKBStats, getDocument, getSource, type ChunkInsert
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

  const gitInfo = await detectGitRepo(folderPath)
  if (gitInfo.isRepo) {
    updateSource(source.id, {
      status: 'indexing',
      git_repo_path: gitInfo.repoPath || null,
      git_branch: gitInfo.branch || null,
      git_commit_hash: gitInfo.commitHash || null
    })
  } else {
    updateSource(source.id, { status: 'indexing' })
  }

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

export interface SyncProgress {
  type: 'start' | 'file' | 'complete' | 'error' | 'nochange'
  sourceId?: string
  fileName?: string
  fileIndex?: number
  totalFiles?: number
  status?: string
  error?: string
  filesChanged?: number
  chunksAdded?: number
  chunksRemoved?: number
}

export async function syncSource(
  kbId: string,
  sourceId: string,
  options?: PipelineOptions,
  onProgress?: (progress: SyncProgress) => void
): Promise<{ filesChanged: number; chunksAdded: number; chunksRemoved: number }> {
  const source = getSource(sourceId)
  if (!source) throw new Error('Source not found')

  const gitInfo = await detectGitRepo(source.path)
  if (!gitInfo.isRepo) {
    onProgress?.({ type: 'nochange', sourceId })
    return { filesChanged: 0, chunksAdded: 0, chunksRemoved: 0 }
  }

  const currentCommit = await getCurrentCommit(source.path)
  if (currentCommit && currentCommit.substring(0, 8) === source.git_commit_hash) {
    onProgress?.({ type: 'nochange', sourceId })
    return { filesChanged: 0, chunksAdded: 0, chunksRemoved: 0 }
  }

  const branch = await getCurrentBranch(source.path)
  const changedFiles = await getChangedFiles(source.path, source.git_commit_hash || undefined)

  if (changedFiles.length === 0) {
    updateSource(sourceId, { git_commit_hash: currentCommit.substring(0, 8), git_branch: branch, git_synced_at: Date.now() })
    onProgress?.({ type: 'nochange', sourceId })
    return { filesChanged: 0, chunksAdded: 0, chunksRemoved: 0 }
  }

  updateSource(sourceId, { status: 'indexing' })
  onProgress?.({ type: 'start', sourceId, totalFiles: changedFiles.length })

  let chunksAdded = 0
  let chunksRemoved = 0
  let filesProcessed = 0

  const docs = listDocuments(kbId)

  for (let i = 0; i < changedFiles.length; i++) {
    const cf = changedFiles[i]
      const fullPath = join(source.path, cf.path)
    onProgress?.({ type: 'file', sourceId, fileName: cf.path, fileIndex: i, totalFiles: changedFiles.length, status: cf.status })

    try {
      if (cf.status === 'D') {
        const doc = docs.find(d => d.path === fullPath)
        if (doc) {
          chunksRemoved += doc.chunk_count
          removeChunksByDoc(doc.id)
          removeDocument(doc.id)
          filesProcessed++
        }
      } else if (cf.status === 'A' || cf.status === 'M') {
        const existingDoc = docs.find(d => d.path === fullPath)

        const { readFile: readFs } = await import('fs/promises')
        let content: string
        try { content = await readFs(fullPath, 'utf-8') } catch { continue }

        const contentHash = getContentHash(content)
        if (existingDoc && existingDoc.indexed_content_hash === contentHash) continue

        const ext = cf.path.split('.').pop() || ''
        const name = cf.path.split('/').pop() || cf.path

        if (existingDoc) {
          chunksRemoved += existingDoc.chunk_count
          removeChunksByDoc(existingDoc.id)
          removeDocument(existingDoc.id)
        }

        const doc = addDocument(kbId, sourceId, fullPath, name, ext, content.length)

        const chunks = semanticChunk(content, fullPath, {
          chunkSize: options?.chunkSize,
          chunkOverlap: options?.chunkOverlap,
          strategy: options?.strategy
        })

        if (chunks.length > 0) {
          const texts = chunks.map(c => c.content)
          const embeddings = await embedBatch(texts, 'passage')

          const chunkInserts: ChunkInsert[] = chunks.map((c, j) => ({
            content: c.content,
            embedding: Array.from(embeddings[j]),
            metadata: c.metadata as unknown as Record<string, unknown>
          }))

          addChunks(doc.id, kbId, chunkInserts)
          chunksAdded += chunks.length
        }

        updateDocument(doc.id, {
          status: 'indexed',
          content_preview: content.substring(0, 500),
          chunk_count: chunks.length,
          indexed_content_hash: contentHash,
          git_status: 'clean'
        })

        filesProcessed++
      }
    } catch (error) {
      onProgress?.({ type: 'error', fileName: cf.path, error: error instanceof Error ? error.message : String(error) })
    }
  }

  updateSource(sourceId, {
    status: 'indexed',
    git_commit_hash: currentCommit.substring(0, 8),
    git_branch: branch,
    git_synced_at: Date.now()
  })
  updateKBStats(kbId)

  onProgress?.({ type: 'complete', sourceId, filesChanged: filesProcessed, chunksAdded, chunksRemoved })
  return { filesChanged: filesProcessed, chunksAdded, chunksRemoved }
}
