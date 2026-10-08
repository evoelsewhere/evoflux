import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SkillRecordingWizard } from '@/components/settings/SkillRecordingWizard'

const mocks = vi.hoisted(() => ({
  listWindows: vi.fn(),
  getDisplayMedia: vi.fn(),
  uploadVideo: vi.fn(),
  startNative: vi.fn(),
  stopNative: vi.fn(),
  pauseNative: vi.fn(),
  resumeNative: vi.fn(),
  checkpointNative: vi.fn(),
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
}))
vi.mock('@/api/client/skillRecordings', () => ({
  createSkillRecording: mocks.createRecording,
  appendSkillRecordingEvents: vi.fn(),
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
  SettingsGroup: ({ title, children, actions }: { title?: string; children: React.ReactNode; actions?: React.ReactNode }) => (
    <section>{title && <h2>{title}</h2>}{actions}{children}</section>
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
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listWindows.mockResolvedValue([{ id: 17, app: 'Editor', title: 'Draft', foreground: true }])
    const track = { stop: vi.fn(), addEventListener: vi.fn() }
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
    mocks.stopNative.mockResolvedValue(undefined)
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

  it('starts desktop capture directly without an app, goal, or model picker', async () => {
    render(<SkillRecordingWizard />)

    expect(mocks.startNative).not.toHaveBeenCalled()
    expect(screen.queryByLabelText('What should this skill help with?')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Model for the draft')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('App window')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Refresh apps' })).not.toBeInTheDocument()
    expect(screen.getByText('Record a desktop workflow')).toBeInTheDocument()
    expect(screen.getByText('Video stays on this device until you review it.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Record a skill' }))

    await waitFor(() => expect(mocks.startNative).toHaveBeenCalledWith(expect.any(String)))
    expect(mocks.getDisplayMedia).toHaveBeenCalledWith({
      video: { displaySurface: 'monitor', frameRate: 15 },
      audio: false,
    })
  })

  it('does not create a recording when the user cancels the Windows screen picker', async () => {
    mocks.getDisplayMedia.mockRejectedValueOnce(new DOMException('Picker dismissed', 'NotAllowedError'))
    render(<SkillRecordingWizard />)

    fireEvent.click(screen.getByRole('button', { name: 'Record a skill' }))

    await waitFor(() => expect(mocks.createRecording).not.toHaveBeenCalled())
    expect(await screen.findByText(/Screen capture was cancelled/)).toBeInTheDocument()
  })

  it('stops a window-only share and asks for Entire screen', async () => {
    const track = { stop: vi.fn(), addEventListener: vi.fn(), getSettings: () => ({ displaySurface: 'window' }) }
    mocks.getDisplayMedia.mockResolvedValueOnce({ getTracks: () => [track], getVideoTracks: () => [track] })
    render(<SkillRecordingWizard />)

    fireEvent.click(screen.getByRole('button', { name: 'Record a skill' }))

    expect(await screen.findByText(/Choose “Entire screen”/)).toBeInTheDocument()
    expect(track.stop).toHaveBeenCalledOnce()
    expect(mocks.createRecording).not.toHaveBeenCalled()
  })

  it('caches the stopped video locally for review', async () => {
    render(<SkillRecordingWizard />)

    expect(screen.getByRole('button', { name: 'Record a skill' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Record a skill' }))

    await screen.findByRole('button', { name: 'Stop recording' })
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))

    await screen.findByText('Review captured actions')
    expect(mocks.uploadSkillRecordingVideo).toHaveBeenCalledWith('record-1', expect.any(Blob))
    expect(screen.getByLabelText('Recording video')).toHaveAttribute(
      'src',
      '/skill-recordings/record-1/video',
    )
  })

  it('keeps the stopped video available for retry if the cache upload fails', async () => {
    mocks.uploadSkillRecordingVideo.mockRejectedValueOnce(new Error('disk busy'))
    render(<SkillRecordingWizard />)

    fireEvent.click(screen.getByRole('button', { name: 'Record a skill' }))
    await screen.findByRole('button', { name: 'Stop recording' })
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))

    const retry = await screen.findByRole('button', { name: 'Retry video save' })
    fireEvent.click(retry)
    await waitFor(() => expect(mocks.uploadSkillRecordingVideo).toHaveBeenCalledTimes(2))
    expect(await screen.findByLabelText('Recording video')).toBeInTheDocument()
  })

  it('opens a new chat with the reviewed trace without asking for a provider', async () => {
    render(<SkillRecordingWizard />)

    fireEvent.click(screen.getByRole('button', { name: 'Record a skill' }))
    await screen.findByRole('button', { name: 'Stop recording' })
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))
    await screen.findByText('Review captured actions')
    expect(screen.queryByLabelText('Workflow goal')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Draft model')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Review trace for chat' }))
    await waitFor(() => expect(mocks.previewDraft).toHaveBeenCalledWith('record-1', {
      selected_event_ids: [1],
      redactions: {},
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
})
