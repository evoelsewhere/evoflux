/// <reference types="vite/client" />

declare module '*.png' { const src: string; export default src }
declare module '*.svg' { const src: string; export default src }

interface Window {
  api: {
    settings: {
      save: (settings: Record<string, unknown>) => Promise<{ success: boolean }>
      load: () => Promise<{ providers: unknown[]; appearance: unknown | null }>
    }
    ai: {
      chat: (messages: Array<{ role: string; content: string }>, options?: { model?: string; provider?: string; providerConfig?: { apiKey?: string; baseUrl?: string } }) => Promise<string>
      streamChat: (messages: Array<{ role: string; content: string }>, options?: { model?: string; provider?: string; providerConfig?: { apiKey?: string; baseUrl?: string } }) => Promise<string>
      listModels: (provider?: string) => Promise<string[]>
      testConnection: (provider: string, providerConfig?: { apiKey?: string; baseUrl?: string }) => Promise<boolean>
      saveModelConfig: (provider: string, model: string, config: unknown) => Promise<{ success: boolean }>
      getModelConfig: (provider: string, model: string) => Promise<Record<string, unknown> | null>
      listModelConfigs: () => Promise<Array<{ provider: string; model: string; config: Record<string, unknown> }>>
    }
    workflow: {
      save: (workflow: unknown) => Promise<unknown>
      saveSync: (workflow: unknown) => { success: boolean; id: string }
      load: (id: string) => Promise<unknown>
      list: () => Promise<unknown[]>
      delete: (id: string) => Promise<boolean>
      run: (dsl: unknown, options?: { inputs?: Record<string, unknown>; maxSteps?: number; maxTimeMs?: number }) => Promise<{ success: boolean; results?: unknown[]; error?: string }>
      stop: (runId?: string) => Promise<boolean>
      onEvent: (callback: (event: unknown) => void) => () => void
    }
    sandbox: {
      create: (config: unknown) => Promise<{ success: boolean; id?: string; rootPath?: string; error?: string }>
      destroy: (workflowId: string, runId?: string) => Promise<{ success: boolean; error?: string }>
      exec: (workflowId: string, command: string, options?: unknown) => Promise<{ success: boolean; stdout?: string; stderr?: string; exitCode?: number; error?: string }>
      execCode: (workflowId: string, language: string, code: string) => Promise<{ success: boolean; stdout?: string; stderr?: string; exitCode?: number; error?: string }>
      readFile: (workflowId: string, filePath: string) => Promise<{ success: boolean; content?: string; error?: string }>
      writeFile: (workflowId: string, filePath: string, content: string) => Promise<{ success: boolean; error?: string }>
    }
    dsl: {
      export: (dsl: unknown) => Promise<{ success: boolean; path?: string; error?: string }>
      import: () => Promise<{ success: boolean; dsl?: unknown; error?: string }>
    }
    memory: {
      search: (workflowId: string, query: string, options?: { k?: number; layer?: string }) => Promise<{ success: boolean; results?: unknown[]; error?: string }>
      addSemantic: (workflowId: string, content: string, type: string, metadata?: unknown) => Promise<{ success: boolean; id?: string; error?: string }>
      recordOutcome: (workflowId: string, outcome: string, feedback: string) => Promise<{ success: boolean; id?: string; error?: string }>
      stats: (workflowId: string) => Promise<{ success: boolean; stats?: unknown; error?: string }>
      consolidate: (workflowId: string) => Promise<{ success: boolean; result?: unknown; error?: string }>
    }
    kb: {
      create: (name: string, description?: string, config?: Record<string, unknown>) => Promise<unknown>
      list: () => Promise<unknown[]>
      get: (id: string) => Promise<unknown>
      update: (id: string, patch: { name?: string; description?: string; config?: Record<string, unknown> }) => Promise<unknown>
      delete: (id: string) => Promise<{ success: boolean }>
      selectFolder: () => Promise<string | null>
      selectFiles: () => Promise<string[] | null>
      addFolder: (kbId: string) => Promise<unknown>
      addFiles: (kbId: string) => Promise<unknown>
      removeSource: (sourceId: string) => Promise<{ success: boolean }>
      listSources: (kbId: string) => Promise<unknown[]>
      listDocuments: (kbId: string) => Promise<unknown[]>
      listChunks: (docId: string) => Promise<unknown[]>
      getStats: (kbId: string) => Promise<unknown>
      search: (kbId: string, query: string, options?: { limit?: number; vectorWeight?: number; bm25Weight?: number }) => Promise<unknown>
      detectGit: (path: string) => Promise<unknown>
      getGitStatus: (sourceId: string) => Promise<unknown>
      getFileDiff: (sourceId: string, filePath: string) => Promise<string>
      syncSource: (kbId: string, sourceId: string) => Promise<unknown>
      setAutoSync: (sourceId: string, enabled: boolean) => Promise<{ success: boolean }>
      export: (kbId: string) => Promise<{ success: boolean; path?: string; error?: string }>
      import: () => Promise<{ success: boolean; kbId?: string; error?: string }>
      onProgress: (callback: (event: unknown) => void) => () => void
    }
    mcp: {
      start: () => Promise<{ success: boolean; error?: string }>
      stop: () => Promise<{ success: boolean; error?: string }>
      status: () => Promise<{ running: boolean }>
    }
    wiki: {
      build: (kbId: string, options?: { providerId?: string; model?: string }) => Promise<{ success?: boolean; entities?: number; relationships?: number; pages?: number; error?: string }>
      stats: (kbId: string) => Promise<{ entities: number; relationships: number; pages: number; built: boolean }>
      entities: (kbId: string, type?: string) => Promise<unknown[]>
      entity: (entityId: string) => Promise<unknown>
      entityRelationships: (entityId: string) => Promise<unknown[]>
      entityChunks: (entityId: string) => Promise<string[]>
      search: (kbId: string, query: string, limit?: number) => Promise<unknown[]>
      pages: (kbId: string) => Promise<unknown[]>
      page: (pageId: string) => Promise<unknown>
      pageByEntity: (entityId: string) => Promise<unknown>
      overview: (kbId: string) => Promise<unknown>
      graph: (kbId: string) => Promise<{ entities: unknown[]; relationships: unknown[] }>
      delete: (kbId: string) => Promise<{ success: boolean }>
      onProgress: (callback: (event: unknown) => void) => () => void
    }
    usecase: {
      list: (projectPath: string) => Promise<Array<{ name: string; description: string; path: string; tags: string[] }> | { error: string }>
      get: (projectPath: string, name: string) => Promise<unknown>
      resolve: (projectPath: string, name: string, kbId: string, input?: string) => Promise<unknown>
      selectFolder: () => Promise<string | null>
      clearCache: () => Promise<{ success: boolean }>
    }
    onStreamChunk: (callback: (chunk: string) => void) => () => void
  }
}
