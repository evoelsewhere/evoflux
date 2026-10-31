import { expect, test } from '@playwright/test'
import { startStack } from '../support/stack'
import { dismissImportDialog, MOCK_REPLY, openApp, sendMessage } from '../support/ui'

// Rollback drill: `edge-stateless=rust` serves the ported routes from Rust,
// `edge-stateless=python` (the rollback) serves them from Python again, and the
// same user journey passes either way. `server: uvicorn` is the Python marker.

test.describe.configure({ mode: 'serial' })

for (const owner of ['rust', 'python'] as const) {
  test(`edge-stateless=${owner}: routes are served by ${owner} and chat still works`, async ({ page }) => {
    test.setTimeout(240_000)
    const stack = await startStack({ routeOverride: `edge-stateless=${owner}` })
    try {
      for (const path of ['/api/health/live', '/api/quote']) {
        const response = await fetch(new URL(path, stack.apiUrl))
        expect(response.status, path).toBe(200)
        expect(response.headers.get('server') === 'uvicorn', `${path} served by Python`).toBe(owner === 'python')
      }
      // Python-owned in both modes.
      const ready = await fetch(new URL('/api/health/ready', stack.apiUrl))
      expect(ready.status).toBe(200)
      expect(ready.headers.get('server')).toBe('uvicorn')

      await openApp(page, stack.webUrl)
      await dismissImportDialog(page)
      await sendMessage(page, `hello from ${owner}`)
      await expect(page.getByText(MOCK_REPLY)).toBeVisible()
    } finally {
      await stack.stop()
    }
  })
}
