import { contextBridge, ipcRenderer } from 'electron'

const api = {
  settings: {
    save: (settings: Record<string, unknown>) => ipcRenderer.invoke('settings:save', settings),
    load: () => ipcRenderer.invoke('settings:load')
  },
  ai: {
    chat: (messages: Array<{ role: string; content: string }>, options?: { model?: string; provider?: string; providerConfig?: { apiKey?: string; baseUrl?: string } }) =>
      ipcRenderer.invoke('ai:chat', messages, options),
    streamChat: (messages: Array<{ role: string; content: string }>, options?: { model?: string; provider?: string; providerConfig?: { apiKey?: string; baseUrl?: string } }) =>
      ipcRenderer.invoke('ai:stream-chat', messages, options),
    listModels: (provider?: string) => ipcRenderer.invoke('ai:list-models', provider),
    testConnection: (provider: string, providerConfig?: { apiKey?: string; baseUrl?: string }) =>
      ipcRenderer.invoke('ai:test-connection', provider, providerConfig),
    saveModelConfig: (provider: string, model: string, config: unknown) =>
      ipcRenderer.invoke('ai:save-model-config', provider, model, config),
    getModelConfig: (provider: string, model: string) =>
      ipcRenderer.invoke('ai:get-model-config', provider, model),
    listModelConfigs: () => ipcRenderer.invoke('ai:list-model-configs')
  },
  workflow: {
    save: (workflow: unknown) => ipcRenderer.invoke('workflow:save', workflow),
    saveSync: (workflow: unknown) => ipcRenderer.sendSync('workflow:saveSync', workflow),
    load: (id: string) => ipcRenderer.invoke('workflow:load', id),
    list: () => ipcRenderer.invoke('workflow:list'),
    delete: (id: string) => ipcRenderer.invoke('workflow:delete', id),
    run: (dsl: unknown, options?: { inputs?: Record<string, unknown>; maxSteps?: number; maxTimeMs?: number }) =>
      ipcRenderer.invoke('workflow:run', dsl, options),
    stop: (runId?: string) => ipcRenderer.invoke('workflow:stop', runId),
    onEvent: (callback: (event: unknown) => void) => {
      const handler = (_event: unknown, data: unknown) => callback(data)
      ipcRenderer.on('workflow:event', handler)
      return () => ipcRenderer.removeListener('workflow:event', handler)
    }
  },
  sandbox: {
    create: (config: unknown) => ipcRenderer.invoke('sandbox:create', config),
    destroy: (workflowId: string, runId?: string) => ipcRenderer.invoke('sandbox:destroy', workflowId, runId),
    exec: (workflowId: string, command: string, options?: unknown) =>
      ipcRenderer.invoke('sandbox:exec', workflowId, command, options),
    execCode: (workflowId: string, language: string, code: string) =>
      ipcRenderer.invoke('sandbox:execCode', workflowId, language, code),
    readFile: (workflowId: string, filePath: string) =>
      ipcRenderer.invoke('sandbox:readFile', workflowId, filePath),
    writeFile: (workflowId: string, filePath: string, content: string) =>
      ipcRenderer.invoke('sandbox:writeFile', workflowId, filePath, content)
  },
  dsl: {
    export: (dsl: unknown) => ipcRenderer.invoke('dsl:export', dsl),
    import: () => ipcRenderer.invoke('dsl:import')
  },
  memory: {
    search: (workflowId: string, query: string, options?: { k?: number; layer?: string }) =>
      ipcRenderer.invoke('memory:search', workflowId, query, options),
    addSemantic: (workflowId: string, content: string, type: string, metadata?: unknown) =>
      ipcRenderer.invoke('memory:addSemantic', workflowId, content, type, metadata),
    recordOutcome: (workflowId: string, outcome: string, feedback: string) =>
      ipcRenderer.invoke('memory:recordOutcome', workflowId, outcome, feedback),
    stats: (workflowId: string) => ipcRenderer.invoke('memory:stats', workflowId),
    consolidate: (workflowId: string) => ipcRenderer.invoke('memory:consolidate', workflowId)
  },
  kb: {
    create: (name: string, description?: string, config?: Record<string, unknown>) =>
      ipcRenderer.invoke('kb:create', name, description, config),
    list: () => ipcRenderer.invoke('kb:list'),
    get: (id: string) => ipcRenderer.invoke('kb:get', id),
    update: (id: string, patch: { name?: string; description?: string; config?: Record<string, unknown> }) =>
      ipcRenderer.invoke('kb:update', id, patch),
    delete: (id: string) => ipcRenderer.invoke('kb:delete', id),
    selectFolder: () => ipcRenderer.invoke('kb:selectFolder'),
    selectFiles: () => ipcRenderer.invoke('kb:selectFiles'),
    addFolder: (kbId: string) => ipcRenderer.invoke('kb:addFolder', kbId),
    addFiles: (kbId: string) => ipcRenderer.invoke('kb:addFiles', kbId),
    removeSource: (sourceId: string) => ipcRenderer.invoke('kb:removeSource', sourceId),
    listSources: (kbId: string) => ipcRenderer.invoke('kb:listSources', kbId),
    listDocuments: (kbId: string) => ipcRenderer.invoke('kb:listDocuments', kbId),
    listChunks: (docId: string) => ipcRenderer.invoke('kb:listChunks', docId),
    getStats: (kbId: string) => ipcRenderer.invoke('kb:getStats', kbId),
    search: (kbId: string, query: string, options?: { limit?: number; vectorWeight?: number; bm25Weight?: number }) =>
      ipcRenderer.invoke('kb:search', kbId, query, options),
    detectGit: (path: string) => ipcRenderer.invoke('kb:detectGit', path),
    getGitStatus: (sourceId: string) => ipcRenderer.invoke('kb:getGitStatus', sourceId),
    getFileDiff: (sourceId: string, filePath: string) => ipcRenderer.invoke('kb:getFileDiff', sourceId, filePath),
    syncSource: (kbId: string, sourceId: string) => ipcRenderer.invoke('kb:syncSource', kbId, sourceId),
    setAutoSync: (sourceId: string, enabled: boolean) => ipcRenderer.invoke('kb:setAutoSync', sourceId, enabled),
    export: (kbId: string) => ipcRenderer.invoke('kb:export', kbId),
    import: () => ipcRenderer.invoke('kb:import'),
    onProgress: (callback: (event: unknown) => void) => {
      const handler = (_event: unknown, data: unknown) => callback(data)
      ipcRenderer.on('kb:event', handler)
      return () => ipcRenderer.removeListener('kb:event', handler)
    }
  },
  mcp: {
    start: () => ipcRenderer.invoke('mcp:start'),
    stop: () => ipcRenderer.invoke('mcp:stop'),
    status: () => ipcRenderer.invoke('mcp:status')
  },
  onStreamChunk: (callback: (chunk: string) => void) => {
    const handler = (_event: unknown, chunk: string) => callback(chunk)
    ipcRenderer.on('ai:stream-chunk', handler)
    return () => ipcRenderer.removeListener('ai:stream-chunk', handler)
  }
}

contextBridge.exposeInMainWorld('api', api)

export type ElectronAPI = typeof api
