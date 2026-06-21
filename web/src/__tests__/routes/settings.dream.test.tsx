import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type { ReactNode } from 'react'

import { ToastStack } from '@/components/ToastStack'
import { useToastStore } from '@/stores/useToastStore'

mock.module('@tanstack/react-router', () => ({
  Link: ({ children }: { children: ReactNode }) => children,
}))

mock.module('@/hooks/use-mobile', () => ({
  useIsMobile: () => false,
}))

import { DreamSettingsPage } from '@/routes/settings.dream'

const server = setupServer()
let originalFetch: typeof fetch | undefined

beforeEach(() => {
  useToastStore.setState({ toasts: [] })
  server.listen()
  originalFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (typeof input === 'string' && input.startsWith('/')) {
      return originalFetch?.(`http://localhost${input}`, init) ?? Promise.reject(new Error('fetch unavailable'))
    }
    return originalFetch?.(input, init) ?? Promise.reject(new Error('fetch unavailable'))
  }) as typeof fetch
})

afterEach(() => {
  server.resetHandlers()
  useToastStore.setState({ toasts: [] })
  if (originalFetch) globalThis.fetch = originalFetch
  originalFetch = undefined
  server.close()
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <DreamSettingsPage />
      <ToastStack />
    </QueryClientProvider>,
  )
}

describe('DreamSettingsPage', () => {
  it('keeps dream controls touch-sized before desktop compact sizing', async () => {
    server.use(
      http.get('http://localhost/api/dream/config', () => HttpResponse.json({
        enabled: true,
        model: 'codex:gpt-5.5',
        schedule: '0 2 * * *',
      })),
      http.get('http://localhost/api/agents/registry', () => HttpResponse.json({
        agents: [],
        skills: [],
        tools: [],
        models: [{ id: 'codex:gpt-5.5' }],
      })),
    )

    renderPage()

    const runNow = screen.getByRole('button', { name: /run now/i })
    expect(runNow.className).toContain('min-h-11')
    expect(runNow.className).toContain('md:min-h-0')

    const save = screen.getByRole('button', { name: /save/i })
    expect(save.className).toContain('min-h-11')
    expect(save.className).toContain('md:min-h-0')

    const enabled = await screen.findByRole('switch', { name: /enabled/i })
    expect(enabled.parentElement?.className).toContain('min-h-11')
    expect(enabled.parentElement?.className).toContain('md:min-h-0')

    const schedule = screen.getByLabelText('Cron expression')
    expect(schedule.className).toContain('min-h-11')
    expect(schedule.className).toContain('md:min-h-9')

    const model = screen.getByRole('combobox')
    expect(model.className).toContain('min-h-11')
    expect(model.className).toContain('md:min-h-9')
  })
})
