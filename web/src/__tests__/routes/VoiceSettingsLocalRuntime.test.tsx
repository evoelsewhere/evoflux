import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getVoiceSettings: vi.fn(),
  listVoiceProviderModels: vi.fn(),
  getLocalSttRuntime: vi.fn(),
  cancelLocalSttInstall: vi.fn(),
  checkLocalSttRuntime: vi.fn(),
  dismissLocalSttError: vi.fn(),
  installLocalSttRuntime: vi.fn(),
  uninstallLocalSttRuntime: vi.fn(),
  saveVoiceSettings: vi.fn(),
  testVoiceProvider: vi.fn(),
}))

vi.mock('@/api/client', () => api)
vi.mock('@/lib/voice-permissions', () => ({ requestVoicePermission: vi.fn() }))
vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => false }))
vi.mock('@/components/settings/SettingsLayout', () => ({
  SettingsGroup: ({ title, description, actions, children }: { title: string; description?: string; actions?: React.ReactNode; children: React.ReactNode }) => (
    <section><h2>{title}</h2>{description && <p>{description}</p>}{actions}{children}</section>
  ),
  SettingsPage: ({ title, lede, actions, children }: { title: string; lede?: string; actions?: React.ReactNode; children: React.ReactNode }) => (
    <main><h1>{title}</h1>{lede && <p>{lede}</p>}{actions}{children}</main>
  ),
}))

import { VoiceSettingsPage } from '@/routes/settings.voice'

describe('VoiceSettingsPage local runtime availability', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { clear: vi.fn(), getItem: vi.fn(() => null), setItem: vi.fn(), removeItem: vi.fn() },
    })
    api.getVoiceSettings.mockResolvedValue({
      providers: [],
      chain: [],
      allow_hosted_fallback: false,
      local_private_only: false,
      adapters: ['openai_compatible', 'local_faster_whisper'],
    })
    api.getLocalSttRuntime.mockResolvedValue({
      available: false,
      state: 'unavailable',
      platform: 'win32-x64',
      model_id: 'faster-whisper-small-multilingual',
      runtime_version: null,
      model_version: null,
      download_bytes: null,
      install_bytes: null,
      installed_runtime_version: null,
      installed_model_version: null,
      healthy: false,
      job: null,
    })
  })

  it('shows the detected host and explains that no download size is published yet', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><VoiceSettingsPage /></QueryClientProvider>)

    expect(await screen.findByText((_, element) => element?.tagName === 'P' && element.textContent?.includes('Windows x64 · download not published') === true)).toBeInTheDocument()
    expect(screen.getByText('Local STT assets are not included in this app release yet. Configured remote/custom speech providers remain available.')).toBeInTheDocument()
  })

  it('starts a new provider with an empty endpoint and a useful placeholder', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><VoiceSettingsPage /></QueryClientProvider>)

    fireEvent.click(await screen.findByRole('button', { name: 'Add provider' }))

    const endpoint = await screen.findByLabelText('Endpoint')
    expect(endpoint).toHaveValue('')
    expect(endpoint).toHaveAttribute('placeholder', 'https://api.groq.com/openai/v1')
  })

  it('loads a saved compatible endpoint catalog and adds the selected model', async () => {
    api.getVoiceSettings.mockResolvedValue({
      providers: [{
        id: 'groq',
        name: 'Groq Whisper',
        adapter: 'openai_compatible',
        base_url: 'https://api.groq.com/openai/v1',
        models: [],
        locale: null,
        enabled: true,
        credential_configured: true,
      }],
      chain: [],
      allow_hosted_fallback: false,
      local_private_only: false,
      adapters: ['openai_compatible', 'local_faster_whisper'],
    })
    api.listVoiceProviderModels.mockResolvedValue({ models: ['whisper-large-v3-turbo'] })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><VoiceSettingsPage /></QueryClientProvider>)

    fireEvent.click(await screen.findByRole('button', { name: 'Load models' }))

    const modelPicker = await screen.findByRole('combobox', { name: 'Available models for Groq Whisper' })
    await waitFor(() => expect(api.listVoiceProviderModels).toHaveBeenCalledWith('groq'))
    fireEvent.change(modelPicker, { target: { value: 'whisper-large-v3-turbo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add model' }))
    expect(screen.getByLabelText('Model IDs (comma separated)')).toHaveValue('whisper-large-v3-turbo')
  })
})
