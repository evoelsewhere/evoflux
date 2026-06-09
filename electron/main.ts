import { app, BrowserWindow, shell, ipcMain } from 'electron'
import { join } from 'path'
import { registerAIHandlers } from './ipc/ai'
import { registerWorkflowHandlers } from './ipc/workflow'
import { registerWorkflowRunnerHandlers, setMainWindow } from './ipc/workflow-runner'
import { registerSandboxHandlers } from './ipc/sandbox'
import { registerDSLHandlers } from './ipc/dsl'
import { registerMemoryHandlers } from './ipc/memory'
import { registerKBHandlers } from './ipc/knowledge-base'
import { openDatabase, closeDatabase, flushDatabase } from '../src/engine/db/database'
import { EvoluxMCPServer } from './mcp/server'

let mainWindow: BrowserWindow | null = null
let mcpServer: EvoluxMCPServer | null = null

function createWindow(): void {
  const isDev = !app.isPackaged

  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#000000',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 12, y: 12 },
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  setMainWindow(mainWindow)

  mainWindow.on('ready-to-show', () => {
    mainWindow?.show()
  })

  mainWindow.on('close', () => {
    flushDatabase()
    mainWindow?.webContents.send('workflow:event', { type: 'app:closing', timestamp: Date.now() })
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  if (isDev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(async () => {
  const dbPath = join(app.getPath('userData'), 'evoflux.db')
  await openDatabase(dbPath)

  createWindow()

  registerAIHandlers()
  registerWorkflowHandlers()
  registerWorkflowRunnerHandlers()
  registerSandboxHandlers()
  registerDSLHandlers()
  registerMemoryHandlers()
  registerKBHandlers()

  mcpServer = new EvoluxMCPServer()

  ipcMain.handle('mcp:start', async () => {
    try {
      if (!mcpServer!.isRunning()) await mcpServer!.startStdio()
      return { success: true }
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('mcp:stop', async () => {
    try {
      await mcpServer!.stop()
      return { success: true }
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  ipcMain.handle('mcp:status', async () => {
    return { running: mcpServer!.isRunning() }
  })

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (mcpServer) mcpServer.stop()
  closeDatabase()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
