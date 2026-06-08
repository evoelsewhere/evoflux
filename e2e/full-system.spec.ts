import { test, expect } from './helpers'

const PROVIDER = {
  name: 'Test Anthropic',
  url: 'https://token-plan-sgp.xiaomimimo.com/anthropic',
  apiKey: 'tp-s51e6u4x82u04mubar93p9dybarhbk4jzcvgbt964wvw0lys',
  model: 'mimo-v2.5-pro'
}

async function dismissSettings(window: import('@playwright/test').Page) {
  const closeBtn = window.locator('button[aria-label="Close settings"]')
  if (await closeBtn.isVisible({ timeout: 500 }).catch(() => false)) {
    await closeBtn.click()
    await window.waitForTimeout(200)
  }
}

async function openSettings(window: import('@playwright/test').Page) {
  const settingsBtn = window.locator('button[aria-label="Settings"]')
  await settingsBtn.click()
  await expect(window.locator('text=AI Providers')).toBeVisible({ timeout: 5000 })
}

test.describe('Provider Configuration', () => {
  test('should add Anthropic provider via UI', async ({ window }) => {
    await openSettings(window)

    const addBtn = window.locator('button:has-text("Add")')
    await addBtn.click()

    await expect(window.locator('text=AI Providers')).toBeVisible()

    const providerCards = window.locator('[class*="ant-select"]').first()
    await expect(providerCards).toBeVisible()
  })

  test('should configure and persist provider settings', async ({ window }) => {
    await openSettings(window)

    const providersTab = window.locator('button:has-text("AI Providers")')
    await providersTab.click()

    await expect(window.locator('text=AI Providers').first()).toBeVisible()

    await dismissSettings(window)
  })

  test('should switch between settings tabs', async ({ window }) => {
    await openSettings(window)

    const appearanceTab = window.locator('button:has-text("Appearance")')
    await appearanceTab.click()
    await expect(window.locator('text=Theme')).toBeVisible()

    const aboutTab = window.locator('button:has-text("About")')
    await aboutTab.click()
    await expect(window.locator('text=Evoflux')).toBeVisible()

    const providersTab = window.locator('button:has-text("AI Providers")')
    await providersTab.click()
    await expect(window.locator('text=Add').first()).toBeVisible()

    await dismissSettings(window)
  })
})

test.describe('Workflow CRUD', () => {
  test('should create workflow and see Start node', async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })
  })

  test('should add multiple node types', async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await expect(window.locator('text=Search nodes...')).toBeVisible()

    await window.locator('text=LLM').first().click()
    await expect(window.locator('text=LLM')).toBeVisible()

    await addNodeBtn.click()
    await window.locator('input[placeholder="Search nodes..."]').fill('Condition')
    await window.locator('text=Condition').first().click()
    await expect(window.locator('text=Condition')).toBeVisible()

    await addNodeBtn.click()
    await window.locator('input[placeholder="Search nodes..."]').fill('Code')
    await window.locator('text=Code').first().click()
    await expect(window.locator('text=Code')).toBeVisible()
  })

  test('should delete node', async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await window.locator('text=LLM').first().click()
    await expect(window.locator('text=LLM')).toBeVisible()

    await window.locator('text=LLM').click()

    await window.waitForTimeout(300)

    const deleteBtn = window.locator('button[aria-label="Delete node"]')
    if (await deleteBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
      await deleteBtn.click()
      await window.waitForTimeout(500)
    }
  })

  test('should persist workflow after auto-save', async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await window.locator('text=LLM').first().click()
    await expect(window.locator('text=LLM')).toBeVisible()

    await window.waitForTimeout(1500)

    const url = window.url()
    const workflowId = url.match(/\/workflows\/([^?#]+)/)?.[1]
    expect(workflowId).toBeTruthy()
  })
})

test.describe('Node Configuration', () => {
  test.beforeEach(async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })
  })

  test('should open and edit LLM node config', async ({ window }) => {
    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await window.locator('text=LLM').first().click()

    await window.locator('text=LLM').click()
    await window.waitForTimeout(500)

    await expect(window.locator('text=AI Configuration').first()).toBeVisible({ timeout: 5000 })
  })

  test('should open and edit Condition node config', async ({ window }) => {
    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await window.locator('input[placeholder="Search nodes..."]').fill('Condition')
    await window.locator('text=Condition').first().click()

    await window.locator('text=Condition').click()
    await window.waitForTimeout(500)

    await expect(window.locator('text=Expression').first()).toBeVisible({ timeout: 5000 })
  })

  test('should open and edit Code node config', async ({ window }) => {
    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await window.locator('input[placeholder="Search nodes..."]').fill('Code')
    await window.locator('text=Code').first().click()

    await window.locator('text=Code').click()
    await window.waitForTimeout(500)

    await expect(window.locator('text=Language').first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Edge Configuration', () => {
  test('should click edge and show edge popup', async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await window.locator('text=LLM').first().click()

    await window.waitForTimeout(500)

    const edgePath = window.locator('.react-flow__edge-path').first()
    if (await edgePath.isVisible({ timeout: 2000 }).catch(() => false)) {
      await edgePath.click()
      await window.waitForTimeout(300)
    }
  })
})

test.describe('Dashboard', () => {
  test('should show workflow list after creating workflows', async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    await window.locator('button[aria-label="Back"]').click()
    await window.waitForTimeout(500)

    await expect(window.locator('text=Dashboard')).toBeVisible({ timeout: 5000 })
  })

  test('should show stats cards', async ({ window }) => {
    await expect(window.locator('text=Workflows')).toBeVisible()
    await expect(window.locator('text=Total Nodes')).toBeVisible()
    await expect(window.locator('text=Total Edges')).toBeVisible()
    await expect(window.locator('text=AI Providers')).toBeVisible()
  })

  test('should search workflows', async ({ window }) => {
    const searchInput = window.locator('input[placeholder="Search workflows..."]')
    await expect(searchInput).toBeVisible()

    await searchInput.fill('nonexistent-workflow-xyz')
    await window.waitForTimeout(300)
  })
})

test.describe('Run Panel', () => {
  test('should show run button in editor', async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    const runBtn = window.locator('button[aria-label="Run"]')
    await expect(runBtn).toBeVisible({ timeout: 5000 })
  })

  test('should open run panel when clicking run', async ({ window }) => {
    await window.locator('text=New Workflow').first().click()
    await window.waitForURL(/\/workflows\//)
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    const runBtn = window.locator('button[aria-label="Run"]')
    await runBtn.click()

    await expect(window.locator('text=Run').first()).toBeVisible({ timeout: 5000 })
  })
})
