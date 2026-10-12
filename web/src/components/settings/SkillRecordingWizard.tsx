import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  AlertCircle,
  CircleStop,
  LoaderCircle,
  MonitorPlay,
  Pause,
  Play,
  Radio,
  ShieldCheck,
  Sparkles,
  Trash2,
} from 'lucide-react'

import {
  appendSkillRecordingEvents,
  createSkillRecording,
  deleteSkillRecording,
  getSkillRecording,
  previewSkillRecordingDraft,
  setSkillRecordingState,
  skillRecordingVideoUrl,
  uploadSkillRecordingVideo,
  type SkillRecordingEvent,
  type SkillRecordingReview,
} from '@/api/client/skillRecordings'
import { SettingsCallout, SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import { SkillRecordingTimeline } from '@/components/settings/SkillRecordingTimeline'
import { Button } from '@/components/ui/button'
import { useSettingsClose } from '@/contexts/SettingsContext'
import {
  listenForSkillRecordingEvents,
  pauseSkillRecording,
  resumeSkillRecording,
  startSkillRecording,
  stopSkillRecording,
} from '@/lib/skill-recording-native'
import { stageSkillRecordingChatHandoff } from '@/lib/skill-recording-chat'
import { useTeamStore } from '@/stores/useTeamStore'

type Stage = 'select' | 'recording' | 'review'
type RecordingStatus = 'recording' | 'paused' | 'stopped'
const MAX_RECORDING_BYTES = 512 * 1024 * 1024

export function SkillRecordingWizard() {
  const navigate = useNavigate()
  const closeSettings = useSettingsClose()
  const [stage, setStage] = useState<Stage>('select')
  const [recordingId, setRecordingId] = useState<string | null>(null)
  const [recordingStatus, setRecordingStatus] = useState<RecordingStatus>('stopped')
  const [events, setEvents] = useState<SkillRecordingEvent[]>([])
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [variables, setVariables] = useState<Record<number, string>>({})
  const [targetLabels, setTargetLabels] = useState<Record<number, string>>({})
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewSkillRecordingDraft>> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [eventCount, setEventCount] = useState(0)
  const [videoAvailable, setVideoAvailable] = useState(false)
  const unlistenRef = useRef<(() => void) | null>(null)
  const queueRef = useRef<SkillRecordingEvent[]>([])
  const flushChainRef = useRef<Promise<void>>(Promise.resolve())
  const recordingIdRef = useRef<string | null>(null)
  const finishingRef = useRef(false)
  const recordingActiveRef = useRef(false)
  const mountedRef = useRef(true)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const displayStreamRef = useRef<MediaStream | null>(null)
  const videoChunksRef = useRef<Blob[]>([])
  const videoBytesRef = useRef(0)
  const pendingVideoRef = useRef<Blob | null>(null)

  const flushEvents = useCallback(async (id: string) => {
    const batch = queueRef.current.splice(0, 64)
    if (!batch.length) return
    const send = flushChainRef.current.then(async () => {
      try {
        await appendSkillRecordingEvents(id, batch)
      } catch (sendError) {
        queueRef.current.unshift(...batch)
        if (mountedRef.current) {
          setError(sendError instanceof Error ? sendError.message : String(sendError))
        }
        throw sendError
      }
    })
    flushChainRef.current = send.catch(() => undefined)
    await send
    if (queueRef.current.length) await flushEvents(id)
  }, [])

  const stopMediaCapture = useCallback(async (): Promise<Blob | null> => {
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      await new Promise<void>((resolve) => {
        const onStop = () => {
          recorder.removeEventListener('stop', onStop)
          resolve()
        }
        recorder.addEventListener('stop', onStop, { once: true })
        recorder.stop()
      })
    }
    const blob = videoChunksRef.current.length
      ? new Blob(videoChunksRef.current, { type: recorder?.mimeType || 'video/webm' })
      : null
    displayStreamRef.current?.getTracks().forEach((track) => track.stop())
    displayStreamRef.current = null
    mediaRecorderRef.current = null
    videoChunksRef.current = []
    videoBytesRef.current = 0
    return blob?.size ? blob : null
  }, [])

  const finishRecording = useCallback(
    async (id: string, stopNative: boolean) => {
      if (finishingRef.current) return
      finishingRef.current = true
      setBusy(true)
      try {
        if (stopNative) await stopSkillRecording(id)
        const video = await stopMediaCapture()
        unlistenRef.current?.()
        unlistenRef.current = null
        await flushChainRef.current
        await flushEvents(id)
        await setSkillRecordingState(id, 'stop')
        if (video) {
          pendingVideoRef.current = video
        }
        if (pendingVideoRef.current) {
          try {
            await uploadSkillRecordingVideo(id, pendingVideoRef.current)
            pendingVideoRef.current = null
            setVideoAvailable(true)
          } catch (uploadError) {
            setError(`The recording stopped, but its local video could not be cached: ${uploadError instanceof Error ? uploadError.message : String(uploadError)}`)
          }
        }
        const recording = await getSkillRecording(id)
        setEvents(recording.events)
        setVideoAvailable(Boolean(recording.video_artifacts?.length))
        setSelectedIds(recording.events.map((event) => event.sequence))
        setRecordingStatus('stopped')
        recordingActiveRef.current = false
        setStage('review')
      } catch (finishError) {
        setError(finishError instanceof Error ? finishError.message : String(finishError))
      } finally {
        finishingRef.current = false
        setBusy(false)
      }
    },
    [flushEvents, stopMediaCapture],
  )

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      const id = recordingIdRef.current
      unlistenRef.current?.()
      unlistenRef.current = null
      if (id && recordingActiveRef.current) {
        recordingActiveRef.current = false
        void (async () => {
          await stopSkillRecording(id).catch(() => undefined)
          const video = await stopMediaCapture().catch(() => null)
          await flushEvents(id).catch(() => undefined)
          await setSkillRecordingState(id, 'stop').catch(() => undefined)
          if (video) await uploadSkillRecordingVideo(id, video).catch(() => undefined)
        })()
      }
    }
  }, [flushEvents, stopMediaCapture])

  const startRecording = async () => {
    setBusy(true)
    setError(null)
    let stream: MediaStream | null = null
    let id: string | null = null
    try {
      if (!navigator.mediaDevices?.getDisplayMedia) {
        throw new Error('Screen recording is available in the EvoFlux Windows desktop app.')
      }
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: 'monitor', frameRate: 15 },
        audio: false,
      })
      const videoTrack = stream.getVideoTracks()[0]
      const selectedSurface = videoTrack?.getSettings?.().displaySurface
      if (!videoTrack) throw new Error('The screen picker did not return a video stream.')
      if (selectedSurface && selectedSurface !== 'monitor') {
        throw new Error('Choose “Entire screen” in the Windows picker to record actions across desktop apps.')
      }
      displayStreamRef.current = stream
      const session = await createSkillRecording()
      id = session.id
      if (!mountedRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        await deleteSkillRecording(session.id).catch(() => undefined)
        return
      }
      recordingIdRef.current = session.id
      queueRef.current = []
      flushChainRef.current = Promise.resolve()
      const unlisten = await listenForSkillRecordingEvents(session.id, (event) => {
        queueRef.current.push(event)
        setEvents((current) => [...current, event])
        setEventCount((count) => count + 1)
        if (queueRef.current.length >= 16) void flushEvents(session.id).catch(() => undefined)
        if (event.kind === 'window_closed') {
          void finishRecording(session.id, false)
        }
      })
      unlistenRef.current = unlisten
      if (!mountedRef.current) {
        unlisten()
        unlistenRef.current = null
        await deleteSkillRecording(session.id).catch(() => undefined)
        recordingIdRef.current = null
        return
      }
      recordingActiveRef.current = true
      await startSkillRecording(session.id)
      if (!mountedRef.current) return
      videoChunksRef.current = []
      videoBytesRef.current = 0
      const mediaType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
        ? 'video/webm;codecs=vp9'
        : 'video/webm'
      const recorder = new MediaRecorder(stream, { mimeType: mediaType })
      recorder.ondataavailable = (event) => {
        if (!event.data.size) return
        if (videoBytesRef.current + event.data.size > MAX_RECORDING_BYTES) {
          setError('This recording reached the local size limit. Stop and review the captured portion.')
          if (recorder.state !== 'inactive') recorder.stop()
          return
        }
        videoBytesRef.current += event.data.size
        videoChunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const currentId = recordingIdRef.current
        if (currentId && recordingActiveRef.current) {
          void finishRecording(currentId, true)
        }
      }
      mediaRecorderRef.current = recorder
      recorder.start(1000)
      videoTrack.addEventListener('ended', () => {
        if (recordingIdRef.current) void finishRecording(recordingIdRef.current, true)
      }, { once: true })
      setRecordingId(session.id)
      setRecordingStatus('recording')
      setStage('recording')
    } catch (startError) {
      const pickerCancelled = startError instanceof DOMException && startError.name === 'NotAllowedError'
      const pendingVideo = await stopMediaCapture().catch(() => null)
      void pendingVideo
      if (stream && !mediaRecorderRef.current) {
        stream.getTracks().forEach((track) => track.stop())
      }
      unlistenRef.current?.()
      unlistenRef.current = null
      if (id) {
        await stopSkillRecording(id).catch(() => undefined)
        await deleteSkillRecording(id).catch(() => undefined)
      }
      recordingIdRef.current = null
      recordingActiveRef.current = false
      setError(
        pickerCancelled
          ? 'Screen capture was cancelled. Press Record when you are ready to choose a display.'
          : startError instanceof Error
            ? startError.message
            : String(startError),
      )
    } finally {
      setBusy(false)
    }
  }

  const pauseRecording = async () => {
    if (!recordingId) return
    setBusy(true)
    setError(null)
    try {
      await pauseSkillRecording(recordingId)
      mediaRecorderRef.current?.pause()
      setRecordingStatus('paused')
      await flushEvents(recordingId)
      await setSkillRecordingState(recordingId, 'pause')
    } catch (pauseError) {
      setError(pauseError instanceof Error ? pauseError.message : String(pauseError))
    } finally {
      setBusy(false)
    }
  }

  const resumeRecording = async () => {
    if (!recordingId) return
    setBusy(true)
    setError(null)
    try {
      await setSkillRecordingState(recordingId, 'resume')
      await resumeSkillRecording(recordingId)
      mediaRecorderRef.current?.resume()
      setRecordingStatus('recording')
    } catch (resumeError) {
      await setSkillRecordingState(recordingId, 'pause').catch(() => undefined)
      setRecordingStatus('paused')
      setError(resumeError instanceof Error ? resumeError.message : String(resumeError))
    } finally {
      setBusy(false)
    }
  }

  const reviewPayload = (): SkillRecordingReview => {
    const redactions: Record<string, string> = {}
    for (const event of events) {
      if (!selectedIds.includes(event.sequence)) continue
      const replacement = variables[event.sequence]
      if (replacement !== undefined && event.value) redactions[event.value] = replacement
      const targetLabel = targetLabels[event.sequence]
      if (targetLabel !== undefined && event.target?.name) redactions[event.target.name] = targetLabel
    }
    return { selected_event_ids: selectedIds, redactions, goal: '' }
  }

  const showPreview = async () => {
    if (!recordingId) return
    setBusy(true)
    setError(null)
    try {
      setPreview(await previewSkillRecordingDraft(recordingId, reviewPayload()))
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : String(previewError))
    } finally {
      setBusy(false)
    }
  }

  const retryVideoUpload = async () => {
    if (!recordingId || !pendingVideoRef.current) return
    setBusy(true)
    setError(null)
    try {
      await uploadSkillRecordingVideo(recordingId, pendingVideoRef.current)
      pendingVideoRef.current = null
      setVideoAvailable(true)
    } catch (uploadError) {
      setError(`The local video still could not be cached: ${uploadError instanceof Error ? uploadError.message : String(uploadError)}`)
    } finally {
      setBusy(false)
    }
  }

  const openInChat = () => {
    if (!recordingId || !preview) return
    useTeamStore.getState().beginResolvedSession(null, { mode: 'work' })
    stageSkillRecordingChatHandoff({ recordingId, payload: preview.payload })
    closeSettings({ force: true })
    void navigate({ to: '/' })
  }

  const removeRecording = async () => {
    if (!recordingId) return
    setBusy(true)
    try {
      await deleteSkillRecording(recordingId)
      recordingIdRef.current = null
      recordingActiveRef.current = false
      pendingVideoRef.current = null
      setRecordingId(null)
      setStage('select')
      setEvents([])
      setPreview(null)
      setVideoAvailable(false)
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : String(deleteError))
    } finally {
      setBusy(false)
    }
  }

  const toggleEvent = (sequence: number) => {
    setSelectedIds((current) =>
      current.includes(sequence)
        ? current.filter((id) => id !== sequence)
        : [...current, sequence].sort((a, b) => a - b),
    )
    setPreview(null)
  }

  const changeVariable = (sequence: number, value: string) => {
    const event = events.find((item) => item.sequence === sequence)
    setVariables((current) => ({ ...current, [sequence]: value === event?.value ? '' : value }))
    setPreview(null)
  }

  const changeTargetLabel = (sequence: number, value: string) => {
    const event = events.find((item) => item.sequence === sequence)
    setTargetLabels((current) => ({ ...current, [sequence]: value === event?.target?.name ? '' : value }))
    setPreview(null)
  }

  const title = 'Create skill from recording'

  return (
    <SettingsPage
      icon={Sparkles}
      title={title}
      lede="Show one desktop workflow, review what was captured, then ask AI to turn it into a reusable skill."
      size="wide"
      actions={
        stage === 'recording' ? (
          <Button variant="destructive" onClick={() => recordingId && void finishRecording(recordingId, true)} disabled={busy}>
            <CircleStop aria-hidden="true" />
            Stop recording
          </Button>
        ) : null
      }
    >
      {error && (
        <SettingsCallout tone="error" icon={AlertCircle}>
          {error}
        </SettingsCallout>
      )}

      {stage === 'select' && (
        <>
          <SettingsGroup
            title="Show us the workflow"
            description="Choose Entire screen in the Windows picker, then do the task in your usual apps."
          >
            <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:p-5">
              <div className="flex min-w-0 items-start gap-3">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-(--color-accent)/20 bg-(--color-accent-soft) text-(--color-accent)">
                  <MonitorPlay size={19} aria-hidden="true" />
                </div>
                <div className="min-w-0 space-y-1">
                  <h3 className="text-sm font-semibold text-(--color-text)">Record a desktop workflow</h3>
                  <p className="text-xs leading-relaxed text-(--color-text-muted)">Review every captured step before using it in chat.</p>
                  <p className="flex items-center gap-1.5 pt-1 text-xs text-(--color-text-muted)">
                    <ShieldCheck size={14} className="shrink-0 text-(--color-success)" aria-hidden="true" />
                    <span>Video stays on this device until you review it.</span>
                  </p>
                </div>
              </div>
              <Button className="w-full shrink-0 sm:w-auto" onClick={() => void startRecording()} disabled={busy}>
                {busy ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Radio aria-hidden="true" />}
                Record a skill
              </Button>
            </div>
          </SettingsGroup>
        </>
      )}

      {stage === 'recording' && (
        <>
          <SettingsCallout tone="warning" icon={Radio}>
            Recording the selected display · {eventCount} events. Video stays local and expires after one hour. Values are captured only from accessibility fields confirmed as non-password.
          </SettingsCallout>
          <SettingsGroup title="Recording controls" description="Pause while entering information you do not want in the demonstration, or stop to review the local recording.">
            <div className="flex flex-wrap items-center gap-2 p-4 sm:p-5">
              {recordingStatus === 'recording' ? (
                <Button variant="outline" onClick={() => void pauseRecording()} disabled={busy}><Pause aria-hidden="true" />Pause</Button>
              ) : (
                <Button variant="outline" onClick={() => void resumeRecording()} disabled={busy}><Play aria-hidden="true" />Resume</Button>
              )}
              <span className="text-xs text-(--color-text-muted)">Events and video are saved on this computer and stay out of chat until you review and send.</span>
            </div>
          </SettingsGroup>
        </>
      )}

      {stage === 'review' && recordingId && (
        <>
          {pendingVideoRef.current && (
            <SettingsCallout tone="warning" icon={AlertCircle}>
              The action trace is saved. Retry caching the video to keep it available for local review.
              <Button className="ml-2" variant="outline" onClick={() => void retryVideoUpload()} disabled={busy}>Retry video save</Button>
            </SettingsCallout>
          )}
          {videoAvailable && (
            <SettingsGroup title="Review the recording" description="This video is local to this computer and is not attached to chat automatically.">
              <div className="p-4 sm:p-5">
                <video
                  aria-label="Recording video"
                  className="max-h-[60vh] w-full rounded-md bg-black"
                  controls
                  preload="metadata"
                  src={skillRecordingVideoUrl(recordingId)}
                />
              </div>
            </SettingsGroup>
          )}
          <SettingsGroup title="Review captured actions" description="Remove steps that do not belong in the skill. Replace sample values with reusable variables before previewing.">
            <SkillRecordingTimeline
              recordingId={recordingId}
              events={events}
              selectedIds={selectedIds}
              variables={variables}
              targetLabels={targetLabels}
              onToggleEvent={toggleEvent}
              onVariableChange={changeVariable}
              onTargetLabelChange={changeTargetLabel}
            />
          </SettingsGroup>
          <SettingsGroup title="Continue in chat" description="Review the exact text that will be attached. It stays local until you send the message from chat; screenshots are excluded.">
            <div className="space-y-3 p-4 sm:p-5">
              {preview ? (
                <>
                  <p className="text-sm font-medium">This exact event text will be attached to a new chat:</p>
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border border-(--color-border) bg-(--bg-key)/50 p-3 font-mono text-xs">{preview.payload}</pre>
                  <div className="flex justify-end">
                    <Button onClick={openInChat}><Sparkles aria-hidden="true" />Open new chat</Button>
                  </div>
                </>
              ) : (
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="max-w-[60ch] text-xs leading-relaxed text-(--color-text-muted)">Filter actions and replace sample values above. Choose the chat model and refine the Skill there; nothing is sent until you press Send.</p>
                  <Button onClick={() => void showPreview()} disabled={busy || !selectedIds.length}>{busy ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : null}Review trace for chat</Button>
                </div>
              )}
              <Button type="button" variant="ghost" onClick={() => void removeRecording()} disabled={busy}><Trash2 aria-hidden="true" />Delete recording</Button>
            </div>
          </SettingsGroup>
        </>
      )}

    </SettingsPage>
  )
}
