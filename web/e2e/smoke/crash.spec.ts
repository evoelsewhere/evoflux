import { expect, test } from '@playwright/test'
import { startStack } from '../support/stack'
import { dismissImportDialog, MOCK_REPLY, openApp, sendMessage } from '../support/ui'

// Crash drill: kill the Python child mid-session. The gateway answers 502 for
// Python-owned routes while the supervisor restarts it (1 s first backoff),
// then everything recovers and the session history is still there.

test('killing the Python child gives a 502 window, then recovery', async ({ page }) => {
  test.setTimeout(300_000)
  const stack = await startStack()
  try {
    await openApp(page, stack.webUrl)
    await dismissImportDialog(page)
    await sendMessage(page, 'before the crash')
    await expect(page.getByText(MOCK_REPLY)).toBeVisible()
    const sessionPath = new URL(page.url()).pathname
    const before = stack.pythonPid()

    stack.killPython()

    const statuses = new Set<number>()
    const deadline = Date.now() + 90_000
    let recovered = false
    while (Date.now() < deadline) {
      let status = 0
      try {
        status = (await fetch(new URL('/api/health/ready', stack.webUrl))).status
      } catch {
        status = 0
      }
      statuses.add(status)
      if (status === 200 && statuses.has(502)) {
        recovered = true
        break
      }
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    expect([...statuses], 'a 502 window was observed').toContain(502)
    expect(recovered, 'the backend recovered after the 502 window').toBe(true)
    expect(stack.pythonPid(), 'the supervisor started a new Python child').not.toBe(before)

    await openApp(page, stack.webUrl, sessionPath)
    await dismissImportDialog(page)
    await expect(page.getByText('before the crash', { exact: true })).toBeVisible()
    await expect(page.getByText(MOCK_REPLY)).toBeVisible()
    await sendMessage(page, 'after the crash')
    await expect(page.getByText('after the crash', { exact: true })).toBeVisible()
    await expect(page.getByText(MOCK_REPLY)).toHaveCount(2)
  } finally {
    await stack.stop()
  }
})
