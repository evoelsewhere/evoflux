import { expect, type Page } from '@playwright/test'

export const MOCK_REPLY = 'Hello from mock.'

/**
 * Open the app with a clean route memory. The browser keeps `oa-last-route*`
 * across data-dir resets and then shows "Session not found" (smoke report,
 * known quirk), so the keys are removed once per tab; the sessionStorage flag
 * keeps a later `reload()` from forgetting the session it is checking.
 */
export async function openApp(page: Page, webUrl: string, path = '/'): Promise<void> {
  await page.addInitScript(() => {
    if (sessionStorage.getItem('e2e-route-cleared')) return
    sessionStorage.setItem('e2e-route-cleared', '1')
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('oa-last-route')) localStorage.removeItem(key)
    }
  })
  await page.goto(new URL(path, webUrl).toString())
  await expect(composer(page)).toBeVisible()
}

export function composer(page: Page) {
  return page.getByPlaceholder(/Ask anything/)
}

export function importDialog(page: Page) {
  return page.getByRole('dialog').filter({ hasText: 'Import your data' })
}

/** Dismiss the first-run import dialog if it is showing (it can appear late). */
export async function dismissImportDialog(page: Page): Promise<void> {
  const dialog = importDialog(page)
  try {
    await dialog.waitFor({ state: 'visible', timeout: 5_000 })
  } catch {
    return
  }
  await dialog.getByRole('button', { name: 'Not now' }).click()
  await expect(dialog).toBeHidden()
}

/**
 * Fill the composer and send with the button. Never call this right after a
 * slash then Backspace: that input path swallows the send (see the test.fixme
 * in journeys.spec.ts), so the composer is filled in one step instead.
 */
export async function sendMessage(page: Page, text: string): Promise<void> {
  const box = composer(page)
  await box.fill(text)
  await expect(box).toHaveValue(text)
  await page.getByRole('button', { name: 'Send message' }).click()
}

export async function expectApiOk(base: string, path: string): Promise<unknown> {
  const response = await fetch(new URL(path, base))
  expect(response.status, `${path} status`).toBe(200)
  return response.json()
}
