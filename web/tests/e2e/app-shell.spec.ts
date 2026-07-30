import { expect, test } from '@playwright/test'

test('loads the application shell without a fatal client error', async ({ page }) => {
  await page.goto('/')

  await expect(page.locator('#root')).toBeVisible()
  await expect(page.locator('body')).not.toContainText('Unexpected Application Error')
})
