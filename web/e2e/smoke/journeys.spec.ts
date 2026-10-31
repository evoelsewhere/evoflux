import { expect, test } from '@playwright/test'
import { type Stack, startStack } from '../support/stack'
import { composer, dismissImportDialog, expectApiOk, importDialog, MOCK_REPLY, openApp, sendMessage } from '../support/ui'

// The design §9a journeys against the default routing, or against the unit
// owner in EVOFLUX_E2E_ROUTE_OVERRIDE (`e2e.sh --route-override <unit>=<owner>`).

test.describe.configure({ mode: 'serial' })

let stack: Stack
let sessionPath = ''

test.beforeAll(async () => {
  test.setTimeout(240_000)
  stack = await startStack({ routeOverride: process.env.EVOFLUX_E2E_ROUTE_OVERRIDE || undefined })
})

test.afterAll(async () => {
  await stack?.stop()
})

test('app loads and the first-run import dialog can be dismissed', async ({ page }) => {
  await openApp(page, stack.webUrl)
  await expect(page.getByText('What would you like to accomplish?')).toBeVisible()
  await expect(importDialog(page)).toBeVisible()
  await page.getByRole('button', { name: 'Not now' }).click()
  await expect(importDialog(page)).toBeHidden()
})

test('the slash menu lists init', async ({ page }) => {
  await openApp(page, stack.webUrl)
  await dismissImportDialog(page)
  await composer(page).fill('/')
  await expect(page.getByText('/init', { exact: true })).toBeVisible()
})

test('a chat streams the mock reply', async ({ page }) => {
  await openApp(page, stack.webUrl)
  await dismissImportDialog(page)
  await sendMessage(page, 'say hello')
  await expect(page.getByText(MOCK_REPLY)).toBeVisible()
  await expect(page).toHaveURL(/\/[0-9a-f-]{36}$/)
  sessionPath = new URL(page.url()).pathname
})

test('the session persists across a reload', async ({ page }) => {
  expect(sessionPath, 'the chat journey must have created a session').not.toBe('')
  await openApp(page, stack.webUrl, sessionPath)
  await dismissImportDialog(page)
  await expect(page.getByText('say hello', { exact: true })).toBeVisible()
  await expect(page.getByText(MOCK_REPLY)).toBeVisible()
  await page.reload()
  await dismissImportDialog(page)
  await expect(page.getByText('say hello', { exact: true })).toBeVisible()
  await expect(page.getByText(MOCK_REPLY)).toBeVisible()
})

test('/api/health/live and /api/quote work through the gateway and the web proxy', async () => {
  for (const base of [stack.apiUrl, stack.webUrl]) {
    expect(await expectApiOk(base, '/api/health/live')).toMatchObject({ status: 'ok', version: expect.any(String) })
    expect(await expectApiOk(base, '/api/quote')).toMatchObject({ quote: expect.any(String), author: expect.any(String) })
  }
})

// Known frontend quirk (phase-1 checkpoint smoke): after typing a slash and
// then Backspace, the next send is consumed and no request leaves the browser.
// The quirk is in the frontend, not the migration; this fixme keeps it tracked.
// Not yet reproduced: the body below passed 3 of 3 (plus button-send and
// menu-open variants) in headless Chromium, so the trigger is still unknown.
// Remove the fixme once a failing sequence is found or the quirk is fixed.
test.fixme('a send right after typing a slash then Backspace goes out', async ({ page }) => {
  await openApp(page, stack.webUrl)
  await dismissImportDialog(page)
  const box = composer(page)
  await box.pressSequentially('/')
  await box.press('Backspace')
  await box.pressSequentially('after backspace')
  const sent = page.waitForRequest((request) => request.method() === 'POST' && request.url().includes('/api/'), { timeout: 10_000 })
  await box.press('Enter')
  await sent
  await expect(page.getByText('after backspace', { exact: true })).toBeVisible()
})
