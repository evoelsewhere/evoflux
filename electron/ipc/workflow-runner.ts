import { ipcMain, BrowserWindow } from 'electron'
import { GraphEngine } from '../../src/engine/graph-engine'
import { VariablePool } from '../../src/engine/variable-pool'
import { UILayer } from '../../src/engine/layers'
import { deserializeGraph } from '../../src/engine/dsl'
import '../../src/engine/nodes/index'

let mainWindow: BrowserWindow | null = null

export function setMainWindow(win: BrowserWindow): void {
  mainWindow = win
}

function sendEvent(event: unknown): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('workflow:event', event)
  }
}

export function registerWorkflowRunnerHandlers(): void {
  ipcMain.handle('workflow:run', async (_event, dsl, options) => {
    try {
      const graph = deserializeGraph(dsl)
      const pool = new VariablePool()

      if (options?.inputs) {
        for (const [key, value] of Object.entries(options.inputs)) {
          pool.set(['start', key], value)
        }
      }

      const uiLayer = new UILayer((event) => sendEvent(event))
      const engine = new GraphEngine({
        graph,
        variablePool: pool,
        layers: [uiLayer],
        maxSteps: options?.maxSteps || 1000,
        maxTimeMs: options?.maxTimeMs || 600000,
        maxNodeIterations: options?.maxNodeIterations || 100
      })

      const results: unknown[] = []

      if (engine.shouldUseRouting()) {
        for await (const event of engine.runWithRouting()) {
          results.push(event)
          sendEvent(event)
        }
      } else {
        for await (const event of engine.runSequential()) {
          results.push(event)
          sendEvent(event)
        }
      }

      return { success: true, results }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      sendEvent({ type: 'graph:error', error: message, timestamp: Date.now() })
      return { success: false, error: message }
    }
  })

  ipcMain.handle('workflow:stop', async (_event, runId) => {
    sendEvent({ type: 'graph:aborted', runId, timestamp: Date.now() })
    return true
  })

  ipcMain.handle('workflow:run:status', async (_event, runId) => {
    return { runId, status: 'unknown' }
  })
}
