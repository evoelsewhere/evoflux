import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SkillRecordingWizard } from '@/components/settings/SkillRecordingWizard'
import type { SkillRecordingEvent } from '@/api/client/skillRecordings'

const mocks = vi.hoisted(() => ({
  listWindows: vi.fn(),
  getDisplayMedia: vi.fn(),
  uploadVideo: vi.fn(),
  startNative: vi.fn(),
  stopNative: vi.fn(),
  pauseNative: vi.fn(),
  resumeNative: vi.fn(),
  checkpointNative: vi.fn(),
  appendEvents: vi.fn(),
  focusApp: vi.fn(),
  listenEvents: vi.fn(),
  createRecording: vi.fn(),
  previewDraft: vi.fn(),
  getRecording: vi.fn(),
  uploadSkillRecordingVideo: vi.fn(),
  setRecordingState: vi.fn(),
  navigate: vi.fn(),
  registerDirty: vi.fn(),
  push: vi.fn(),
  beginResolvedSession: vi.fn(),
  closeSettings: vi.fn(),
  stageChatHandoff: vi.fn(),
}))

vi.mock('@/lib/skill-recording-native', () => ({
  listSkillRecordingWindows: mocks.listWindows,
  startSkillRecording: mocks.startNative,
  listenForSkillRecordingEvents: mocks.listenEvents,
  stopSkillRecording: mocks.stopNative,
  pauseSkillRecording: mocks.pauseNative,
  resumeSkillRecording: mocks.resumeNative,
  checkpointSkillRecording: mocks.checkpointNative,
  focusEvofluxAfterSkillRecording: mocks.focusApp,
}))
vi.mock('@/api/client/skillRecordings', () => ({
  createSkillRecording: mocks.createRecording,
  appendSkillRecordingEvents: mocks.appendEvents,
  deleteSkillRecording: vi.fn(),
  getSkillRecording: mocks.getRecording,
  uploadSkillRecordingVideo: mocks.uploadSkillRecordingVideo,
  previewSkillRecordingDraft: mocks.previewDraft,
  setSkillRecordingState: mocks.setRecordingState,
  skillRecordingScreenshotUrl: vi.fn(() => ''),
  skillRecordingVideoUrl: vi.fn(() => '/skill-recordings/record-1/video'),
}))

class MockMediaRecorder {
  static isTypeSupported = vi.fn(() => true)
  state: 'inactive' | 'recording' | 'paused' = 'inactive'
  ondataavailable: ((event: BlobEvent) => void) | null = null
  onstop: (() => void) | null = null
  private listeners = new Map<string, Set<EventListener>>()
  readonly stream: MediaStream

  constructor(stream: MediaStream) { this.stream = stream }
  addEventListener(type: string, listener: EventListener) {
    const listeners = this.listeners.get(type) ?? new Set<EventListener>()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }
  removeEventListener(type: string, listener: EventListener) {
    this.listeners.get(type)?.delete(listener)
  }
  start() { this.state = 'recording' }
  stop() {
    this.ondataavailable?.({ data: new Blob(['synthetic-webm'], { type: 'video/webm' }) } as BlobEvent)
    this.state = 'inactive'
    this.onstop?.()
    this.listeners.get('stop')?.forEach((listener) => listener(new Event('stop')))
  }
  pause() { this.state = 'paused' }
  resume() { this.state = 'recording' }
}
vi.mock('@tanstack/react-router', () => ({ useNavigate: () => mocks.navigate }))
vi.mock('@/contexts/SettingsContext', () => ({
  useSettingsClose: () => mocks.closeSettings,
}))
vi.mock('@/stores/useTeamStore', () => ({
  useTeamStore: { getState: () => ({ beginResolvedSession: mocks.beginResolvedSession }) },
}))
vi.mock('@/lib/skill-recording-chat', () => ({
  stageSkillRecordingChatHandoff: mocks.stageChatHandoff,
}))
vi.mock('@/lib/settings-dirty', () => ({ useRegisterSettingsDirty: mocks.registerDirty }))
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (value: { push: typeof mocks.push }) => unknown) => selector({ push: mocks.push }),
}))
vi.mock('@/components/settings/SettingsLayout', () => ({
  SettingsPage: ({ children, actions }: { children: React.ReactNode; actions?: React.ReactNode }) => (
    <main>{actions}{children}</main>
  ),
  SettingsGroup: ({ title, description, children, actions }: { title?: string; description?: string; children: React.ReactNode; actions?: React.ReactNode }) => (
    <section>{title && <h2>{title}</h2>}{description && <p>{description}</p>}{actions}{children}</section>
  ),
  SettingsCallout: ({ children }: { children: React.ReactNode }) => <aside>{children}</aside>,
}))
vi.mock('@/components/settings/SkillBundleEditor', () => ({
  SkillBundleEditor: ({ skillContent, onSkillContentChange }: {
    skillContent: string
    onSkillContentChange: (content: string) => void
  }) => <textarea aria-label="SKILL.md source" value={skillContent} onChange={(event) => onSkillContentChange(event.target.value)} />,
}))

describe('SkillRecordingWizard', () => {
  const renderWizard = () => render(<SkillRecordingWizard open onOpenChange={vi.fn()} />)
  let onShareEnded: (() => void) | undefined
  let emitRecordingEvent: ((event: SkillRecordingEvent) => void) | undefined

  afterEach(() => vi.restoreAllMocks())

  beforeEach(() => {
    vi.clearAllMocks()
    onShareEnded = undefined
    emitRecordingEvent = undefined
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    mocks.listWindows.mockResolvedValue([{ id: 17, app: 'Editor', title: 'Draft', foreground: true }])
    const track = {
      stop: vi.fn(),
      addEventListener: vi.fn((event: string, listener: () => void) => {
        if (event === 'ended') onShareEnded = listener
      }),
    }
    mocks.getDisplayMedia.mockResolvedValue({ getTracks: () => [track], getVideoTracks: () => [track] })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: mocks.getDisplayMedia },
    })
    Object.defineProperty(globalThis, 'MediaRecorder', {
      configurable: true,
      value: MockMediaRecorder,
    })
    mocks.uploadSkillRecordingVideo.mockResolvedValue({ byte_length: 14 })
    mocks.createRecording.mockResolvedValue({ id: 'record-1' })
    mocks.listenEvents.mockResolvedValue(vi.fn())
    mocks.appendEvents.mockResolvedValue({ accepted: 1 })
    mocks.stopNative.mockResolvedValue(undefined)
    mocks.focusApp.mockResolvedValue(undefined)
    mocks.setRecordingState.mockResolvedValue({ status: 'stopped' })
    mocks.getRecording.mockResolvedValue({
      id: 'record-1',
      status: 'stopped',
      video_artifacts: [{ id: 'video', path: 'video.webm', media_type: 'video/webm', byte_length: 14 }],
      events: [{
        sequence: 1,
        elapsed_ms: 50,
        kind: 'invoked',
        target: { automation_id: 'export', control_type: 'button', name: 'Export' },
        value_state: 'not_captured',
        value: null,
        screenshot: null,
      }],
    })
    mocks.previewDraft.mockResolvedValue({
      payload: '{"goal":"","events":[]}',
      provider_model: null,
      sha256: 'a'.repeat(64),
    })
  })

  it('shows a short preflight popup and starts capture when confirmed', async () => {
    render(<SkillRecordingWizard open onOpenChange={vi.fn()} />)

    const popup = await screen.findByRole('dialog')
    expect(popup).toHaveTextContent(/Choose Entire screen when prompted/)
    expect(popup).toHaveTextContent(/Video and captured actions stay on this device until you review them/)
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument()
    expect(document.querySelector('[data-slot="dialog-overlay"]')).toHaveClass(
      'bg-black/50',
      'backdrop-blur-[2px]',
    )

    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))

    await waitFor(() => expect(mocks.startNative).toHaveBeenCalledWith(expect.any(String)))
    expect(mocks.getDisplayMedia).toHaveBeenCalledWith({
      video: { displaySurface: 'monitor', frameRate: 15 },
      audio: false,
    })
  })

  it('starts desktop capture directly without an app, goal, or model picker', async () => {
    renderWizard()

    expect(mocks.startNative).not.toHaveBeenCalled()
    expect(screen.queryByLabelText('What should this skill help with?')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Model for the draft')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('App window')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Refresh apps' })).not.toBeInTheDocument()
    expect(screen.getByText('Record a skill')).toBeInTheDocument()
    expect(screen.getByText(/Video and captured actions stay on this device until you review them/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))

    await waitFor(() => expect(mocks.startNative).toHaveBeenCalledWith(expect.any(String)))
    expect(mocks.getDisplayMedia).toHaveBeenCalledWith({
      video: { displaySurface: 'monitor', frameRate: 15 },
      audio: false,
    })
  })

  it('does not create a recording when the user cancels the Windows screen picker', async () => {
    mocks.getDisplayMedia.mockRejectedValueOnce(new DOMException('Picker dismissed', 'NotAllowedError'))
    renderWizard()

    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))

    await waitFor(() => expect(mocks.createRecording).not.toHaveBeenCalled())
    expect(await screen.findByText(/Screen capture was cancelled/)).toBeInTheDocument()
  })

  it('stops a window-only share and asks for Entire screen', async () => {
    const track = { stop: vi.fn(), addEventListener: vi.fn(), getSettings: () => ({ displaySurface: 'window' }) }
    mocks.getDisplayMedia.mockResolvedValueOnce({ getTracks: () => [track], getVideoTracks: () => [track] })
    renderWizard()

    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))

    expect(await screen.findByText(/The picker selected a single app window instead of the entire screen/)).toBeInTheDocument()
    expect(track.stop).toHaveBeenCalledOnce()
    expect(mocks.createRecording).not.toHaveBeenCalled()
  })

  it('caches the stopped video locally for review', async () => {
    renderWizard()

    expect(screen.getByRole('button', { name: 'Start recording' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))

    await screen.findByRole('button', { name: 'Stop recording' })
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))

    await screen.findByText('Review captured actions')
    expect(mocks.uploadSkillRecordingVideo).toHaveBeenCalledWith('record-1', expect.any(Blob))
    expect(screen.getByLabelText('Recording video')).toHaveAttribute(
      'src',
      '/skill-recordings/record-1/video',
    )
    await waitFor(() => expect(mocks.focusApp).toHaveBeenCalledOnce())
  })

  it('returns EvoFlux to the foreground when the user stops screen sharing', async () => {
    renderWizard()
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))
    await screen.findByRole('button', { name: 'Stop recording' })

    onShareEnded?.()

    await screen.findByText('Review captured actions')
    await waitFor(() => expect(mocks.focusApp).toHaveBeenCalledOnce())
    expect(mocks.stopNative).toHaveBeenCalledWith('record-1')
  })

  it('shows a download path when the embedded video cannot be decoded', async () => {
    renderWizard()
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))
    await screen.findByRole('button', { name: 'Stop recording' })
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))

    const video = await screen.findByLabelText('Recording video')
    fireEvent.error(video)

    expect(await screen.findByText(/The video could not be played here/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download video' })).toHaveAttribute(
      'href',
      '/skill-recordings/record-1/video',
    )
  })

  it('keeps the stopped video available for retry if the cache upload fails', async () => {
    mocks.uploadSkillRecordingVideo.mockRejectedValueOnce(new Error('disk busy'))
    renderWizard()

    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))
    await screen.findByRole('button', { name: 'Stop recording' })
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))

    const retry = await screen.findByRole('button', { name: 'Retry video save' })
    fireEvent.click(retry)
    await waitFor(() => expect(mocks.uploadSkillRecordingVideo).toHaveBeenCalledTimes(2))
    expect(await screen.findByLabelText('Recording video')).toBeInTheDocument()
  })

  it('opens a new chat with the reviewed trace without asking for a provider', async () => {
    renderWizard()

    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))
    await screen.findByRole('button', { name: 'Stop recording' })
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))
    await screen.findByText('Review captured actions')
    expect(screen.queryByLabelText('Workflow goal')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Draft model')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Review trace for chat' }))
    await waitFor(() => expect(mocks.previewDraft).toHaveBeenCalledWith('record-1', {
      selected_event_ids: [1],
      redactions: {},
      reviewed_input_values: [],
      goal: '',
    }))
    await screen.findByText(/will be attached to a new chat/)
    fireEvent.click(screen.getByRole('button', { name: 'Open new chat' }))

    expect(mocks.stageChatHandoff).toHaveBeenCalledWith({
      recordingId: 'record-1',
      payload: '{"goal":"","events":[]}',
    })
    expect(mocks.beginResolvedSession).toHaveBeenCalledWith(null, { mode: 'work' })
    expect(mocks.closeSettings).toHaveBeenCalledWith({ force: true })
    expect(mocks.navigate).toHaveBeenCalledWith({ to: '/' })
  })

  it('keeps typed text out of stored events until the user reviews selected inputs', async () => {
    mocks.listenEvents.mockImplementationOnce(async (...args: unknown[]) => {
      emitRecordingEvent = args[1] as (event: SkillRecordingEvent) => void
      return vi.fn()
    })
    mocks.getRecording.mockResolvedValueOnce({
      id: 'record-1',
      status: 'stopped',
      video_artifacts: [],
      events: [{
        sequence: 1,
        source_sequence: 17,
        elapsed_ms: 800,
        kind: 'value_changed',
        window: { app: 'browser.exe', title: 'Search' },
        target: { automation_id: 'query', control_type: 'Edit', name: null, label: 'Search query' },
        value_state: 'unavailable',
        value: null,
        screenshot: null,
      }],
    })
    renderWizard()
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))
    await screen.findByRole('button', { name: 'Stop recording' })

    emitRecordingEvent?.({
      sequence: 17,
      elapsed_ms: 800,
      kind: 'value_changed',
      window: { app: 'browser.exe', title: 'Search' },
      target: { automation_id: 'query', control_type: 'Edit', name: null, label: 'Search query' },
      value_state: 'captured',
      value: 'international news',
      screenshot: null,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))
    await screen.findByText('Review captured actions')

    expect(mocks.appendEvents).toHaveBeenCalledWith('record-1', [
      expect.objectContaining({ kind: 'value_changed', value_state: 'unavailable', value: null }),
    ])
    expect(screen.getByRole('textbox', { name: 'Value for event 1' })).toHaveValue('international news')

    fireEvent.click(screen.getByRole('button', { name: 'Review trace for chat' }))
    await waitFor(() => expect(mocks.previewDraft).toHaveBeenCalledWith('record-1', {
      selected_event_ids: [1],
      redactions: {},
      reviewed_input_values: [{ sequence: 1, value: 'international news' }],
      goal: '',
    }))
  })

  it('sends only selected screen frames with the reviewed chat handoff', async () => {
    mocks.getRecording.mockResolvedValueOnce({
      id: 'record-1',
      status: 'stopped',
      video_artifacts: [{ id: 'video', path: 'video.webm', media_type: 'video/webm', byte_length: 14 }],
      events: [
        {
          sequence: 1,
          elapsed_ms: 50,
          kind: 'click',
          point: { x: 10, y: 20, display_id: null },
          button: 'left',
          target: null,
          value_state: 'not_captured',
          value: null,
          screenshot: null,
        },
        {
          sequence: 2,
          elapsed_ms: 51,
          kind: 'screenshot',
          target: { automation_id: null, control_type: 'screen frame', name: 'After left click at (10, 20)' },
          value_state: 'not_captured',
          value: null,
          screenshot: 'screenshots/000002.png',
        },
      ],
    })
    renderWizard()

    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))
    await screen.findByRole('button', { name: 'Stop recording' })
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))
    await screen.findByText('Review captured actions')
    fireEvent.click(screen.getByRole('button', { name: 'Review trace for chat' }))
    await screen.findByText(/selected screen frames will be attached/)
    fireEvent.click(screen.getByRole('button', { name: 'Open new chat' }))

    expect(mocks.stageChatHandoff).toHaveBeenCalledWith({
      recordingId: 'record-1',
      payload: '{"goal":"","events":[]}',
      screenshotSequences: [2],
    })
  })
})
