import { test as base, type ElectronApplication, type Page, _electron as electron } from '@playwright/test'
import { resolve } from 'path'

type ElectronFixtures = {
  electronApp: ElectronApplication
  window: Page
}

export const test = base.extend<ElectronFixtures>({
  electronApp: async ({}, use) => {
    const app = await electron.launch({
      args: [resolve(__dirname, '../out/main/index.js')],
      env: {
        ...process.env,
        NODE_ENV: 'test'
      }
    })
    await use(app)
    await app.close()
  },

  window: async ({ electronApp }, use) => {
    const win = await electronApp.firstWindow()
    await win.waitForLoadState('domcontentloaded')
    await use(win)
  }
})

export { expect } from '@playwright/test'
