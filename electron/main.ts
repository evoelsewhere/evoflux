import { app, BrowserWindow, shell } from 'electron'
import { join } from 'path'
import { registerAIHandlers } from './ipc/ai'
import { registerWorkflowHandlers } from './ipc/workflow'
import { registerWorkflowRunnerHandlers, setMainWindow } from './ipc/workflow-runner'
import { registerSandboxHandlers } from './ipc/sandbox'
import { registerDSLHandlers } from './ipc/dsl'
import { registerMemoryHandlers } from './ipc/memory'
import { openDatabase, closeDatabase } from '../src/engine/db/database'

let mainWindow: BrowserWindow | null = null

function createWindow(): void {
  const isDev = !app.isPackaged

  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    autoHideMenuBar: true,
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

app.whenReady().then(() => {
  const dbPath = join(app.getPath('userData'), 'evoflux.db')
  openDatabase(dbPath)

  createWindow()

  registerAIHandlers()
  registerWorkflowHandlers()
  registerWorkflowRunnerHandlers()
  registerSandboxHandlers()
  registerDSLHandlers()
  registerMemoryHandlers()

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  closeDatabase()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
