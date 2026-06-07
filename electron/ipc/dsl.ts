import { ipcMain, dialog } from 'electron'
import { readFile, writeFile } from 'fs/promises'

export function registerDSLHandlers(): void {
  ipcMain.handle('dsl:export', async (_event, dsl) => {
    try {
      const result = await dialog.showSaveDialog({
        title: 'Export Workflow',
        defaultPath: `${dsl.name || 'workflow'}.json`,
        filters: [{ name: 'JSON', extensions: ['json'] }]
      })

      if (result.canceled || !result.filePath) return { success: false, error: 'Cancelled' }

      await writeFile(result.filePath, JSON.stringify(dsl, null, 2), 'utf-8')
      return { success: true, path: result.filePath }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Export failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('dsl:import', async () => {
    try {
      const result = await dialog.showOpenDialog({
        title: 'Import Workflow',
        filters: [{ name: 'JSON', extensions: ['json'] }],
        properties: ['openFile']
      })

      if (result.canceled || result.filePaths.length === 0) return { success: false, error: 'Cancelled' }

      const content = await readFile(result.filePaths[0], 'utf-8')
      const dsl = JSON.parse(content)
      return { success: true, dsl }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Import failed'
      return { success: false, error: message }
    }
  })
}
