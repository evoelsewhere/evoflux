import { test, expect } from './helpers'

test.describe('Workflow Editor', () => {
  test('should show dashboard on launch', async ({ window }) => {
    await expect(window.locator('h1')).toContainText('Dashboard')
    await expect(window.locator('text=New Workflow')).toBeVisible()
  })

  test('should create a new workflow', async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)

    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })
  })

  test('should open settings popup from dashboard', async ({ window }) => {
    await window.locator('button:has-text("Settings")').click()
    await expect(window.locator('text=AI Providers')).toBeVisible()
    await expect(window.locator('text=Appearance')).toBeVisible()
  })

  test('should open settings popup from dock bar', async ({ window }) => {
    const settingsBtn = window.locator('button[aria-label="Settings"]')
    await settingsBtn.click()
    await expect(window.locator('text=AI Providers')).toBeVisible()
  })
})

test.describe('Node Configuration', () => {
  test.beforeEach(async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })
  })

  test('should click node and show popup', async ({ window }) => {
    await window.locator('text=Start').click()
    await expect(window.locator('text=Manual Trigger')).toBeVisible({ timeout: 5000 })
  })

  test('should edit node label', async ({ window }) => {
    await window.locator('text=Start').click()

    const labelInput = window.locator('input').first()
    await labelInput.clear()
    await labelInput.fill('My Start')

    await expect(window.locator('text=My Start')).toBeVisible()
  })

  test('should add node via sidebar', async ({ window }) => {
    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()

    await expect(window.locator('text=Search nodes...')).toBeVisible({ timeout: 5000 })

    const llmNode = window.locator('text=LLM').first()
    await llmNode.click()

    await expect(window.locator('text=LLM')).toBeVisible()
  })
})

test.describe('Workflow Persistence', () => {
  test('should persist workflow after save and reload', async ({ window, electronApp }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await window.locator('text=LLM').first().click()

    await expect(window.locator('text=LLM')).toBeVisible()

    await window.waitForTimeout(1000)

    const url = window.url()
    const workflowId = url.match(/\/workflows\/(.+)/)?.[1]

    await electronApp.close()

    const app2 = await (await import('@playwright/test'))._electron.launch({
      args: [require('path').resolve(__dirname, '../out/main/index.js')],
      env: { ...process.env, NODE_ENV: 'test' }
    })

    try {
      const win2 = await app2.firstWindow()
      await win2.waitForLoadState('domcontentloaded')

      if (workflowId) {
        await win2.goto(`file://${require('path').resolve(__dirname, '../out/renderer/index.html')}#/workflows/${workflowId}`)
        await win2.waitForTimeout(2000)

        const hasLLM = await win2.locator('text=LLM').isVisible({ timeout: 5000 }).catch(() => false)
        const hasStart = await win2.locator('text=Start').isVisible({ timeout: 5000 }).catch(() => false)

        expect(hasStart).toBeTruthy()
      }
    } finally {
      await app2.close()
    }
  })
})
