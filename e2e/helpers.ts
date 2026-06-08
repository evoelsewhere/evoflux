import { test as base, type ElectronApplication, type Page, _electron as electron } from '@playwright/test'
import { resolve } from 'path'

type ElectronFixtures = {
  electronApp: ElectronApplication
  window: Page
}

export const test = base.extend<ElectronFixtures>({
  electronApp: async ({}, use) => {
    const electronPath = require('electron') as string
    const env = { ...process.env }
    delete env.ELECTRON_RUN_AS_NODE

    const app = await electron.launch({
      executablePath: electronPath,
      args: [resolve(__dirname, '../out/main/index.js')],
      env
    })
    await use(app)
    await app.close()
  },

  window: async ({ electronApp }, use) => {
    const win = await electronApp.firstWindow()
    await win.waitForLoadState('domcontentloaded')
    await win.waitForTimeout(2000)
    await use(win)
  }
})

export { expect } from '@playwright/test'
