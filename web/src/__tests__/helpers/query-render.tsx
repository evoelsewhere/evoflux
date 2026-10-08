import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render as renderTestingLibrary, type RenderOptions } from '@testing-library/react'

export function renderWithQueryClient(ui: ReactElement, options?: Omit<RenderOptions, 'wrapper'>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderTestingLibrary(ui, {
    ...options,
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  })
}
