"use strict";
const electron = require("electron");
const api = {
  settings: {
    save: (settings) => electron.ipcRenderer.invoke("settings:save", settings),
    load: () => electron.ipcRenderer.invoke("settings:load")
  },
  ai: {
    chat: (messages, options) => electron.ipcRenderer.invoke("ai:chat", messages, options),
    streamChat: (messages, options) => electron.ipcRenderer.invoke("ai:stream-chat", messages, options),
    listModels: (provider) => electron.ipcRenderer.invoke("ai:list-models", provider),
    testConnection: (provider, providerConfig) => electron.ipcRenderer.invoke("ai:test-connection", provider, providerConfig),
    saveModelConfig: (provider, model, config) => electron.ipcRenderer.invoke("ai:save-model-config", provider, model, config),
    getModelConfig: (provider, model) => electron.ipcRenderer.invoke("ai:get-model-config", provider, model),
    listModelConfigs: () => electron.ipcRenderer.invoke("ai:list-model-configs")
  },
  workflow: {
    save: (workflow) => electron.ipcRenderer.invoke("workflow:save", workflow),
    load: (id) => electron.ipcRenderer.invoke("workflow:load", id),
    list: () => electron.ipcRenderer.invoke("workflow:list"),
    delete: (id) => electron.ipcRenderer.invoke("workflow:delete", id),
    run: (dsl, options) => electron.ipcRenderer.invoke("workflow:run", dsl, options),
    stop: (runId) => electron.ipcRenderer.invoke("workflow:stop", runId),
    onEvent: (callback) => {
      const handler = (_event, data) => callback(data);
      electron.ipcRenderer.on("workflow:event", handler);
      return () => electron.ipcRenderer.removeListener("workflow:event", handler);
    }
  },
  sandbox: {
    create: (config) => electron.ipcRenderer.invoke("sandbox:create", config),
    destroy: (workflowId, runId) => electron.ipcRenderer.invoke("sandbox:destroy", workflowId, runId),
    exec: (workflowId, command, options) => electron.ipcRenderer.invoke("sandbox:exec", workflowId, command, options),
    execCode: (workflowId, language, code) => electron.ipcRenderer.invoke("sandbox:execCode", workflowId, language, code),
    readFile: (workflowId, filePath) => electron.ipcRenderer.invoke("sandbox:readFile", workflowId, filePath),
    writeFile: (workflowId, filePath, content) => electron.ipcRenderer.invoke("sandbox:writeFile", workflowId, filePath, content)
  },
  dsl: {
    export: (dsl) => electron.ipcRenderer.invoke("dsl:export", dsl),
    import: () => electron.ipcRenderer.invoke("dsl:import")
  },
  memory: {
    search: (workflowId, query, options) => electron.ipcRenderer.invoke("memory:search", workflowId, query, options),
    addSemantic: (workflowId, content, type, metadata) => electron.ipcRenderer.invoke("memory:addSemantic", workflowId, content, type, metadata),
    recordOutcome: (workflowId, outcome, feedback) => electron.ipcRenderer.invoke("memory:recordOutcome", workflowId, outcome, feedback),
    stats: (workflowId) => electron.ipcRenderer.invoke("memory:stats", workflowId),
    consolidate: (workflowId) => electron.ipcRenderer.invoke("memory:consolidate", workflowId)
  },
  onStreamChunk: (callback) => {
    const handler = (_event, chunk) => callback(chunk);
    electron.ipcRenderer.on("ai:stream-chunk", handler);
    return () => electron.ipcRenderer.removeListener("ai:stream-chunk", handler);
  }
};
electron.contextBridge.exposeInMainWorld("api", api);
