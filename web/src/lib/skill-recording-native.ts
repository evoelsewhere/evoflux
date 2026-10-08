import { invoke } from '@tauri-apps/api/core'
import type { SkillRecordingEvent, SkillRecordingWindow } from '@/api/client/skillRecordings'

export async function listSkillRecordingWindows(): Promise<SkillRecordingWindow[]> {
  return invoke<SkillRecordingWindow[]>('app_skill_recording_windows')
}

export async function startSkillRecording(recordingId: string, windowId?: number): Promise<void> {
  await invoke(
    'app_skill_recording_start',
    windowId === undefined ? { recordingId } : { recordingId, windowId },
  )
}

export async function pauseSkillRecording(recordingId: string): Promise<void> {
  await invoke('app_skill_recording_pause', { recordingId })
}

export async function resumeSkillRecording(recordingId: string): Promise<void> {
  await invoke('app_skill_recording_resume', { recordingId })
}

export async function checkpointSkillRecording(recordingId: string): Promise<void> {
  await invoke('app_skill_recording_checkpoint', { recordingId })
}

export async function stopSkillRecording(recordingId: string): Promise<void> {
  await invoke('app_skill_recording_stop', { recordingId })
}

export async function listenForSkillRecordingEvents(
  recordingId: string,
  callback: (event: SkillRecordingEvent) => void,
): Promise<() => void> {
  const { listen } = await import('@tauri-apps/api/event')
  return listen<{ recording_id: string; event: SkillRecordingEvent }>(
    'skill-recording:event',
    ({ payload }) => {
      if (payload.recording_id === recordingId) callback(payload.event)
    },
  )
}
