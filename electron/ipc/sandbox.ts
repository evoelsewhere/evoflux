import { ipcMain } from 'electron'
import { createSandbox, destroySandbox, getSandbox } from '../../src/engine/sandbox/sandbox'

export function registerSandboxHandlers(): void {
  ipcMain.handle('sandbox:create', async (_event, config) => {
    try {
      const sandbox = await createSandbox(config)
      return { success: true, id: sandbox.id, rootPath: sandbox.rootPath }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create sandbox'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('sandbox:destroy', async (_event, workflowId, runId) => {
    try {
      await destroySandbox(workflowId, runId)
      return { success: true }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to destroy sandbox'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('sandbox:exec', async (_event, workflowId, command, options) => {
    try {
      const sandbox = getSandbox(workflowId)
      if (!sandbox) throw new Error('Sandbox not found')
      const result = await sandbox.exec(command, options)
      return { success: true, ...result }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Execution failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('sandbox:execCode', async (_event, workflowId, language, code) => {
    try {
      const sandbox = getSandbox(workflowId)
      if (!sandbox) throw new Error('Sandbox not found')
      const result = await sandbox.execCode(language, code)
      return { success: true, ...result }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Code execution failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('sandbox:readFile', async (_event, workflowId, filePath) => {
    try {
      const sandbox = getSandbox(workflowId)
      if (!sandbox) throw new Error('Sandbox not found')
      const content = await sandbox.readFile(filePath)
      return { success: true, content }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Read failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('sandbox:writeFile', async (_event, workflowId, filePath, content) => {
    try {
      const sandbox = getSandbox(workflowId)
      if (!sandbox) throw new Error('Sandbox not found')
      await sandbox.writeFile(filePath, content)
      return { success: true }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Write failed'
      return { success: false, error: message }
    }
  })
}
