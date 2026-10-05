import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'

import { setApiBaseUrl } from '@/api/base-url'

vi.mock('@/hooks/useThemePreference', () => ({
  useThemePreference: () => ({ resolved: 'dark' }),
}))

import { ProviderBrandIcon } from '@/components/providers/ProviderBrandIcon'

beforeEach(() => {
  Object.defineProperty(window, '__OAD_TOKEN__', {
    value: 'desktop-test-token',
    writable: true,
    configurable: true,
  })
  setApiBaseUrl('http://127.0.0.1:40123')
})

afterEach(() => {
  Object.defineProperty(window, '__OAD_TOKEN__', {
    value: undefined,
    writable: true,
    configurable: true,
  })
  Object.defineProperty(window, '__OAD_API_BASE_URL__', {
    value: undefined,
    writable: true,
    configurable: true,
  })
})

describe('ProviderBrandIcon', () => {
  it('loads catalogue logos from the injected backend with the desktop token', () => {
    const { container } = render(<ProviderBrandIcon providerId="router9" />)
    const image = container.querySelector('img')

    expect(image?.src).toBe(
      'http://127.0.0.1:40123/api/settings/providers/router9/logo?color=%2360A5FA&_token=desktop-test-token',
    )
  })
})
