import { ipcMain, BrowserWindow, dialog } from 'electron'
import {
  createKB, getKB, listKBs, updateKB, deleteKB,
  listSources, removeSource, updateSource, getSource,
  listDocuments, listChunks, getKBStats,
  searchChunksByVector, exportKB, importKB
} from '../../src/engine/db/kb-repo'
import {
  listEntities, getEntity, searchEntities, getEntityByName,
  listRelationships, listPages, getPage, getPageByEntity, getOverviewPage,
  getWikiStats, deleteWikiByKB, getEntityChunkIds
} from '../../src/engine/db/wiki-repo'
import { buildWiki } from '../../src/engine/kb/wiki-builder'
import { hybridSearch } from '../../src/engine/kb/hybrid-search'
import { indexFolder, indexFiles, syncSource } from '../../src/engine/kb/pipeline'
import { detectGitRepo, getChangedFiles, getFileDiff, watchGitRepo } from '../../src/engine/kb/git-ops'

let mainWindow: BrowserWindow | null = null

export function setMainWindow(win: BrowserWindow): void {
  mainWindow = win
}

function sendKBEvent(event: unknown): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('kb:event', event)
  }
}

export function registerKBHandlers(): void {
  ipcMain.handle('kb:create', async (_event, name, description, config) => {
    return createKB(name, description, config)
  })

  ipcMain.handle('kb:list', async () => {
    return listKBs()
  })

  ipcMain.handle('kb:get', async (_event, id) => {
    return getKB(id) || null
  })

  ipcMain.handle('kb:update', async (_event, id, patch) => {
    updateKB(id, patch)
    return getKB(id)
  })

  ipcMain.handle('kb:delete', async (_event, id) => {
    deleteKB(id)
    return { success: true }
  })

  ipcMain.handle('kb:selectFolder', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory'],
      title: 'Select folder to index'
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  ipcMain.handle('kb:selectFiles', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile', 'multiSelections'],
      title: 'Select files to index',
      filters: [
        { name: 'Documents', extensions: ['md', 'txt', 'pdf', 'docx', 'xlsx', 'pptx'] },
        { name: 'Code', extensions: ['js', 'ts', 'py', 'go', 'rs', 'java', 'cpp', 'c'] },
        { name: 'Data', extensions: ['json', 'yaml', 'yml', 'csv', 'xml', 'toml'] },
        { name: 'All Files', extensions: ['*'] }
      ]
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths
  })

  ipcMain.handle('kb:addFolder', async (_event, kbId) => {
    const folderPath = await dialog.showOpenDialog({
      properties: ['openDirectory'],
      title: 'Select folder to index'
    })
    if (folderPath.canceled || folderPath.filePaths.length === 0) return null

    const path = folderPath.filePaths[0]
    try {
      const result = await indexFolder(kbId, path, undefined, (progress) => {
        sendKBEvent({ ...progress, type: 'kb:progress', timestamp: Date.now() })
      })
      return result
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('kb:addFiles', async (_event, kbId) => {
    const fileResult = await dialog.showOpenDialog({
      properties: ['openFile', 'multiSelections'],
      title: 'Select files to index',
      filters: [
        { name: 'Documents', extensions: ['md', 'txt', 'pdf', 'docx', 'xlsx', 'pptx'] },
        { name: 'Code', extensions: ['js', 'ts', 'py', 'go', 'rs', 'java', 'cpp', 'c'] },
        { name: 'Data', extensions: ['json', 'yaml', 'yml', 'csv', 'xml', 'toml'] },
        { name: 'All Files', extensions: ['*'] }
      ]
    })
    if (fileResult.canceled || fileResult.filePaths.length === 0) return null

    try {
      const result = await indexFiles(kbId, fileResult.filePaths, undefined, (progress) => {
        sendKBEvent({ ...progress, type: 'kb:progress', timestamp: Date.now() })
      })
      return result
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('kb:removeSource', async (_event, sourceId) => {
    removeSource(sourceId)
    return { success: true }
  })

  ipcMain.handle('kb:listSources', async (_event, kbId) => {
    return listSources(kbId)
  })

  ipcMain.handle('kb:listDocuments', async (_event, kbId) => {
    return listDocuments(kbId)
  })

  ipcMain.handle('kb:listChunks', async (_event, docId) => {
    return listChunks(docId)
  })

  ipcMain.handle('kb:getStats', async (_event, kbId) => {
    return getKBStats(kbId)
  })

  ipcMain.handle('kb:search', async (_event, kbId, query, options) => {
    try {
      return await hybridSearch(kbId, query, options)
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('kb:detectGit', async (_event, path) => {
    return detectGitRepo(path)
  })

  ipcMain.handle('kb:getGitStatus', async (_event, sourceId) => {
    const source = getSource(sourceId)
    if (!source) return { error: 'Source not found' }
    try {
      const changed = await getChangedFiles(source.path, source.git_commit_hash || undefined)
      return { changes: changed, commitHash: source.git_commit_hash, branch: source.git_branch }
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('kb:getFileDiff', async (_event, sourceId, filePath) => {
    const source = getSource(sourceId)
    if (!source) return { error: 'Source not found' }
    try {
      return await getFileDiff(source.path, filePath, source.git_commit_hash || undefined)
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('kb:syncSource', async (_event, kbId, sourceId) => {
    try {
      const result = await syncSource(kbId, sourceId, undefined, (progress) => {
        sendKBEvent({ ...progress, type: 'kb:sync', timestamp: Date.now() })
      })
      return result
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('kb:setAutoSync', async (_event, sourceId, enabled) => {
    updateSource(sourceId, { auto_sync: enabled ? 1 : 0 })
    return { success: true }
  })

  ipcMain.handle('kb:export', async (_event, kbId) => {
    try {
      const backup = exportKB(kbId)
      const result = await dialog.showSaveDialog({
        title: 'Export Knowledge Base',
        defaultPath: `${backup.kb.name.replace(/[^a-z0-9]/gi, '_')}.kb.json`,
        filters: [{ name: 'Knowledge Base', extensions: ['kb.json'] }]
      })
      if (result.canceled || !result.filePath) return { success: false }

      const { writeFile } = await import('fs/promises')
      await writeFile(result.filePath, JSON.stringify(backup, null, 2), 'utf-8')
      return { success: true, path: result.filePath }
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('kb:import', async () => {
    try {
      const result = await dialog.showOpenDialog({
        title: 'Import Knowledge Base',
        filters: [{ name: 'Knowledge Base', extensions: ['kb.json'] }],
        properties: ['openFile']
      })
      if (result.canceled || result.filePaths.length === 0) return { success: false }

      const { readFile } = await import('fs/promises')
      const content = await readFile(result.filePaths[0], 'utf-8')
      const backup = JSON.parse(content)
      const newKbId = importKB(backup)
      return { success: true, kbId: newKbId }
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  // ==================== Wiki ====================

  ipcMain.handle('wiki:build', async (_event, kbId, options) => {
    try {
      const kb = getKB(kbId)
      if (!kb) return { error: 'KB not found' }

      let config: Record<string, unknown> = {}
      try { config = JSON.parse(kb.config_json) } catch {}
      const wikiConfig = (config.wiki || {}) as Record<string, unknown>

      const providerId = options?.providerId || wikiConfig.providerId
      const model = options?.model || wikiConfig.model
      if (!providerId) return { error: 'No provider configured for wiki. Set provider in KB Settings > Wiki Graph.' }

      const aiChat = (globalThis as any).__evolux_ai_chat
      if (!aiChat) return { error: 'AI chat not available' }

      const result = await buildWiki(kbId, { providerId, model: model as string }, aiChat, (progress) => {
        sendKBEvent({ ...progress, type: 'wiki:progress', timestamp: Date.now() })
      })

      return { success: true, ...result }
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('wiki:stats', async (_event, kbId) => {
    return getWikiStats(kbId)
  })

  ipcMain.handle('wiki:entities', async (_event, kbId, type) => {
    return listEntities(kbId, type)
  })

  ipcMain.handle('wiki:entity', async (_entity, entityId) => {
    return getEntity(entityId) || null
  })

  ipcMain.handle('wiki:entityRelationships', async (_event, entityId) => {
    const entity = getEntity(entityId)
    if (!entity) return []
    return listRelationships(entity.kb_id, entityId)
  })

  ipcMain.handle('wiki:entityChunks', async (_event, entityId) => {
    return getEntityChunkIds(entityId)
  })

  ipcMain.handle('wiki:search', async (_event, kbId, query, limit) => {
    return searchEntities(kbId, query, limit || 20)
  })

  ipcMain.handle('wiki:pages', async (_event, kbId) => {
    return listPages(kbId)
  })

  ipcMain.handle('wiki:page', async (_event, pageId) => {
    return getPage(pageId) || null
  })

  ipcMain.handle('wiki:pageByEntity', async (_event, entityId) => {
    return getPageByEntity(entityId) || null
  })

  ipcMain.handle('wiki:overview', async (_event, kbId) => {
    return getOverviewPage(kbId) || null
  })

  ipcMain.handle('wiki:graph', async (_event, kbId) => {
    const entities = listEntities(kbId)
    const relationships = listRelationships(kbId)
    return { entities, relationships }
  })

  ipcMain.handle('wiki:delete', async (_event, kbId) => {
    deleteWikiByKB(kbId)
    return { success: true }
  })
}
