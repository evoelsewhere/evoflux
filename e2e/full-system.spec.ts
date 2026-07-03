import { test, expect } from './helpers'

test.describe('Provider Configuration', () => {
  test('should open settings and switch tabs', async ({ window }) => {
    await expect(window.locator('text=Dashboard')).toBeVisible({ timeout: 10000 })

    await window.locator('button:has-text("Settings")').click()
    await expect(window.locator('text=AI Providers')).toBeVisible()

    await window.locator('button:has-text("Appearance")').click()
    await expect(window.locator('text=Theme')).toBeVisible()

    await window.locator('button:has-text("About")').click()
    await expect(window.locator('text=Evoflux')).toBeVisible()

    await window.locator('button:has-text("AI Providers")').click()
    await expect(window.locator('text=Add').first()).toBeVisible()
  })

  test('should add provider via settings', async ({ window }) => {
    await expect(window.locator('text=Dashboard')).toBeVisible({ timeout: 10000 })

    await window.locator('button:has-text("Settings")').click()
    await expect(window.locator('text=AI Providers')).toBeVisible()

    await window.locator('button:has-text("Add")').click()
    await window.waitForTimeout(500)
  })
})

test.describe('Workflow CRUD', () => {
  test('should create workflow with multiple nodes', async ({ window }) => {
    await expect(window.locator('text=Dashboard')).toBeVisible({ timeout: 10000 })
    await window.locator('text=New Workflow').first().click()
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

    await addNodeBtn.click()
    await window.locator('input[placeholder="Search nodes..."]').fill('HTTP')
    await window.locator('text=HTTP Request').first().click()
    await expect(window.locator('text=HTTP Request')).toBeVisible()
  })

  test('should navigate back to dashboard', async ({ window }) => {
    await expect(window.locator('text=Dashboard')).toBeVisible({ timeout: 10000 })
    await window.locator('text=New Workflow').first().click()
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    await window.locator('button[aria-label="Back"]').click()
    await expect(window.locator('text=Dashboard')).toBeVisible({ timeout: 5000 })
  })

  test('should show stats on dashboard', async ({ window }) => {
    await expect(window.locator('text=Workflows')).toBeVisible({ timeout: 10000 })
    await expect(window.locator('text=Total Nodes')).toBeVisible()
    await expect(window.locator('text=Total Edges')).toBeVisible()
  })
})

test.describe('Node Config Forms', () => {
  test.beforeEach(async ({ window }) => {
    await expect(window.locator('text=Dashboard')).toBeVisible({ timeout: 10000 })
    await window.locator('text=New Workflow').first().click()
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })
  })

  test('should open LLM config form', async ({ window }) => {
    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await window.locator('text=LLM').first().click()

    await window.locator('text=LLM').click()
    await window.waitForTimeout(500)

    await expect(window.locator('text=AI Configuration').first()).toBeVisible({ timeout: 5000 })
  })

  test('should open Condition config form', async ({ window }) => {
    const addNodeBtn = window.locator('button[aria-label="Add Node"]')
    await addNodeBtn.click()
    await window.locator('input[placeholder="Search nodes..."]').fill('Condition')
    await window.locator('text=Condition').first().click()

    await window.locator('text=Condition').click()
    await window.waitForTimeout(500)

    await expect(window.locator('text=Expression').first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Run Panel', () => {
  test('should show run button', async ({ window }) => {
    await expect(window.locator('text=Dashboard')).toBeVisible({ timeout: 10000 })
    await window.locator('text=New Workflow').first().click()
    await expect(window.locator('text=Start')).toBeVisible({ timeout: 10000 })

    const runBtn = window.locator('button[aria-label="Run"]')
    await expect(runBtn).toBeVisible({ timeout: 5000 })
  })
})
