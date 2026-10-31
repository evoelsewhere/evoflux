import { expect, test } from '@playwright/test'
import { startStack } from '../support/stack'
import { dismissImportDialog, openApp, sendMessage } from '../support/ui'

// Optional checkpoint pass (`checkpoint.sh --real-model`): the chat journey with
// the owner's own provider config. The config is a temp copy made by
// checkpoint.sh and deleted when it exits. Only a non-empty streamed assistant
// reply is asserted; nothing from the config is logged.

const realConfigDir = process.env.EVOFLUX_E2E_REAL_CONFIG_DIR
test.skip(!realConfigDir, 'EVOFLUX_E2E_REAL_CONFIG_DIR is not set')

test('a chat with the real provider streams a non-empty reply', async ({ page }) => {
  test.setTimeout(300_000)
  const stack = await startStack({ realConfigDir })
  try {
    await openApp(page, stack.webUrl)
    await dismissImportDialog(page)
    const prompt = 'Reply with one short sentence.'
    await sendMessage(page, prompt)
    // The footer under a finished reply ends with "<n> tokens".
    await expect(page.getByText(/\d[\d,.]*\s*tokens$/).first()).toBeVisible({ timeout: 180_000 })
    const paragraphs = await page.locator('main p').allInnerTexts()
    const reply = paragraphs.map((text) => text.trim()).filter((text) => text !== '' && text !== prompt)
    expect(reply.length, 'a non-empty assistant reply was rendered').toBeGreaterThan(0)
  } finally {
    await stack.stop()
  }
})
