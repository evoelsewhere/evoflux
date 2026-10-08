import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as apiClient from '@/api/client'
import { InputBar } from '@/components/InputBar'

let stopTrack: ReturnType<typeof vi.fn>

class MockMediaRecorder {
  static lastInstance: MockMediaRecorder | null = null
  static isTypeSupported = () => true
  state: 'inactive' | 'recording' = 'inactive'
  mimeType = 'audio/webm'
  ondataavailable: ((event: BlobEvent) => void) | null = null
  onstop: (() => void) | null = null

  constructor(_stream: MediaStream, _options?: MediaRecorderOptions) {
    MockMediaRecorder.lastInstance = this
  }

  start() {
    this.state = 'recording'
  }

  stop() {
    if (this.state !== 'recording') return
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['sample'], { type: this.mimeType }) } as BlobEvent)
    this.onstop?.()
  }
}

describe('InputBar voice recording', () => {
  let queryClient: QueryClient
  let getUserMedia: ReturnType<typeof vi.fn>

  beforeEach(() => {
    const storedValues = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        get length() { return storedValues.size },
        clear: () => storedValues.clear(),
        getItem: (key: string) => storedValues.get(key) ?? null,
        key: (index: number) => [...storedValues.keys()][index] ?? null,
        removeItem: (key: string) => { storedValues.delete(key) },
        setItem: (key: string, value: string) => { storedValues.set(key, String(value)) },
      } satisfies Storage,
    })
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
    })
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.spyOn(apiClient, 'getVoiceSettings').mockResolvedValue({
      providers: [],
      chain: [{ provider_id: 'local', model_id: 'whisper' }],
      allow_hosted_fallback: false,
      local_private_only: false,
      adapters: ['openai_compatible'],
    })
    stopTrack = vi.fn()
    getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    })
    vi.stubGlobal('MediaRecorder', MockMediaRecorder)
    MockMediaRecorder.lastInstance = null
  })

  afterEach(() => {
    queryClient.clear()
    vi.unstubAllGlobals()
  })

  it('uses mobile tap-to-toggle and discards a late transcript after switching sessions', async () => {
    let finishTranscription!: (value: { text: string; provider_id: string; model_id: string; fallback_used: boolean }) => void
    const transcribe = vi.spyOn(apiClient, 'transcribeVoiceRecording').mockImplementation(() => new Promise((resolve) => {
      finishTranscription = resolve
    }))
    const onSubmit = vi.fn()
    const input = (sessionId: string) => (
      <QueryClientProvider client={queryClient}>
        <InputBar sessionId={sessionId} onSubmit={onSubmit} />
      </QueryClientProvider>
    )
    const view = render(input('session-one'))
    const message = await screen.findByRole('textbox', { name: 'Message input' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Hold to record voice input' })).toBeInTheDocument())
    const voiceButton = screen.getByRole('button', { name: 'Hold to record voice input' })
    const sendButton = screen.getByRole('button', { name: 'Send message' })
    expect(voiceButton.parentElement).toBe(sendButton.parentElement)
    expect(voiceButton.nextElementSibling).toBe(sendButton)
    fireEvent.change(message, { target: { value: 'Keep this in the first chat' } })

    const tap = () => {
      const button = screen.getByRole('button', { name: /^(Stop recording|Hold to record voice input)/i })
      fireEvent.pointerDown(button, { pointerType: 'touch', button: 0 })
      fireEvent.pointerUp(button, { pointerType: 'touch', button: 0 })
      fireEvent.click(button)
    }

    tap()
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1))
    expect(MockMediaRecorder.lastInstance?.state).toBe('recording')
    tap()
    await waitFor(() => expect(transcribe).toHaveBeenCalledTimes(1))

    view.rerender(input('session-two'))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message input' })).toHaveValue(''))
    await act(async () => {
      finishTranscription({ text: 'Transcript from the old chat', provider_id: 'local', model_id: 'whisper', fallback_used: false })
    })

    expect(screen.getByRole('textbox', { name: 'Message input' })).toHaveValue('')
    view.rerender(input('session-one'))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message input' })).toHaveValue('Keep this in the first chat'))
  })

  it('inserts a mobile voice transcript into the current draft for review', async () => {
    vi.spyOn(apiClient, 'transcribeVoiceRecording').mockResolvedValue({
      text: 'Add voice transcript',
      provider_id: 'local',
      model_id: 'whisper',
      fallback_used: false,
    })
    render(
      <QueryClientProvider client={queryClient}>
        <InputBar sessionId="session-one" onSubmit={vi.fn()} />
      </QueryClientProvider>,
    )

    const message = await screen.findByRole('textbox', { name: 'Message input' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Hold to record voice input' })).toBeInTheDocument())
    fireEvent.change(message, { target: { value: 'Existing draft' } })

    const tap = () => {
      const button = screen.getByRole('button', { name: /^(Stop recording|Hold to record voice input)/i })
      fireEvent.pointerDown(button, { pointerType: 'touch', button: 0 })
      fireEvent.pointerUp(button, { pointerType: 'touch', button: 0 })
      fireEvent.click(button)
    }

    tap()
    await waitFor(() => expect(MockMediaRecorder.lastInstance?.state).toBe('recording'))
    tap()

    await waitFor(() => expect(message).toHaveValue('Existing draft Add voice transcript'))
  })

  it('records while held on desktop, inserts the transcript, and releases microphone tracks', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
    })
    Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', { configurable: true, value: vi.fn() })
    vi.spyOn(apiClient, 'transcribeVoiceRecording').mockResolvedValue({
      text: 'Desktop transcript',
      provider_id: 'local',
      model_id: 'whisper',
      fallback_used: false,
    })
    render(
      <QueryClientProvider client={queryClient}>
        <InputBar sessionId="session-one" onSubmit={vi.fn()} />
      </QueryClientProvider>,
    )

    const message = await screen.findByRole('textbox', { name: 'Message input' })
    fireEvent.change(message, { target: { value: 'Draft text' } })
    const voiceButton = await screen.findByRole('button', { name: 'Hold to record voice input' })

    fireEvent.pointerDown(voiceButton, { pointerId: 1, pointerType: 'mouse', button: 0 })
    await waitFor(() => expect(MockMediaRecorder.lastInstance?.state).toBe('recording'))
    fireEvent.pointerUp(voiceButton, { pointerId: 1, pointerType: 'mouse', button: 0 })
    fireEvent.click(voiceButton)

    await waitFor(() => expect(message).toHaveValue('Draft text Desktop transcript'))
    expect(apiClient.transcribeVoiceRecording).toHaveBeenCalledOnce()
    expect(stopTrack).toHaveBeenCalledOnce()
  })
})
