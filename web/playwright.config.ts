import { defineConfig } from '@playwright/test'

// The end-to-end smoke suite (design §9a). `scripts/migration/e2e.sh` builds the
// backend and exports the EVOFLUX_E2E_* variables read by e2e/support/stack.ts.
export default defineConfig({
  testDir: './e2e/smoke',
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 45_000 },
  retries: 0,
  reporter: [['list']],
  use: { actionTimeout: 15_000, navigationTimeout: 30_000, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  outputDir: './e2e/.results',
})
