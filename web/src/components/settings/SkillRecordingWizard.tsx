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
import { SettingsCallout, SettingsGroup } from '@/components/settings/SettingsLayout'
import { SkillRecordingTimeline } from '@/components/settings/SkillRecordingTimeline'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useSettingsClose } from '@/contexts/SettingsContext'
import {
  focusEvofluxAfterSkillRecording,
  listenForSkillRecordingEvents,
  pauseSkillRecording,
  resumeSkillRecording,
  startSkillRecording,
  stopSkillRecording,
} from '@/lib/skill-recording-native'
import { stageSkillRecordingChatHandoff } from '@/lib/skill-recording-chat'
import {
  createActionScreenFrame,
  MAX_AUTO_SCREENSHOTS,
  MIN_SCREENSHOT_INTERVAL_MS,
  shouldCaptureActionFrame,
} from '@/lib/skill-recording-screen-frame'
import { useTeamStore } from '@/stores/useTeamStore'

type Stage = 'select' | 'recording' | 'review'
type RecordingStatus = 'recording' | 'paused' | 'stopped'
const MAX_RECORDING_BYTES = 512 * 1024 * 1024

interface SkillRecordingWizardProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SkillRecordingWizard({ open, onOpenChange }: SkillRecordingWizardProps) {
  const navigate = useNavigate()
  const closeSettings = useSettingsClose()
  const [stage, setStage] = useState<Stage>('select')
  const [recordingId, setRecordingId] = useState<string | null>(null)
  const [recordingStatus, setRecordingStatus] = useState<RecordingStatus>('stopped')
  const [events, setEvents] = useState<SkillRecordingEvent[]>([])
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [variables, setVariables] = useState<Record<number, string>>({})
  const [targetLabels, setTargetLabels] = useState<Record<number, string>>({})
  const [windowTitles, setWindowTitles] = useState<Record<number, string>>({})
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewSkillRecordingDraft>> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [eventCount, setEventCount] = useState(0)
  const [videoAvailable, setVideoAvailable] = useState(false)
  const unlistenRef = useRef<(() => void) | null>(null)
  const queueRef = useRef<SkillRecordingEvent[]>([])
  const reviewedInputValuesRef = useRef<Map<number, string>>(new Map())
  const pendingInputEventsRef = useRef<Map<string, SkillRecordingEvent>>(new Map())
  const inputDebounceTimerRef = useRef<number | null>(null)
  const flushChainRef = useRef<Promise<void>>(Promise.resolve())
  const recordingIdRef = useRef<string | null>(null)
  const finishingRef = useRef(false)
  const recordingActiveRef = useRef(false)
  const mountedRef = useRef(true)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const displayStreamRef = useRef<MediaStream | null>(null)
  const screenPreviewRef = useRef<HTMLVideoElement | null>(null)
  const videoChunksRef = useRef<Blob[]>([])
  const videoBytesRef = useRef(0)
  const pendingVideoRef = useRef<Blob | null>(null)
  const lastScreenshotAtRef = useRef(-MIN_SCREENSHOT_INTERVAL_MS)
  const screenshotCountRef = useRef(0)
  const pendingScreenshotTasksRef = useRef<Promise<void>[]>([])
  const [videoPlaybackError, setVideoPlaybackError] = useState(false)
  const localEventsRef = useRef<SkillRecordingEvent[]>([])

  const flushEvents = useCallback(async (id: string) => {
    const frameIndex = queueRef.current.findIndex((event) => event.kind === 'screenshot')
    const batch = frameIndex === 0
      ? queueRef.current.splice(0, 1)
      : queueRef.current.splice(0, frameIndex < 0 ? 64 : frameIndex)
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

  const captureActionFrame = useCallback(async (action: SkillRecordingEvent) => {
    const video = screenPreviewRef.current
    if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth) return
    await new Promise<void>((resolve) => window.setTimeout(resolve, 120))
    const scale = Math.min(1, 1440 / video.videoWidth)
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) return
    context.drawImage(video, 0, 0, canvas.width, canvas.height)
    const image = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!image) return
    const encoded = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onerror = () => reject(reader.error ?? new Error('Could not encode screen frame.'))
      reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
      reader.readAsDataURL(image)
    })
    if (!encoded || encoded.length > 3 * 1024 * 1024) return
    const frame = createActionScreenFrame(action, encoded)
    queueRef.current.push(frame)
    localEventsRef.current.push(frame)
    setEvents((current) => [...current, frame])
    const id = recordingIdRef.current
    if (id) void flushEvents(id).catch(() => undefined)
  }, [flushEvents])

  const recordEvent = useCallback((event: SkillRecordingEvent) => {
    if (event.kind === 'value_changed' && event.value_state === 'captured' && event.value != null) {
      reviewedInputValuesRef.current.set(event.sequence, event.value)
    }
    const eventForStorage = event.kind === 'value_changed' && event.value_state === 'captured'
      ? { ...event, value_state: 'unavailable' as const, value: null }
      : event
    queueRef.current.push(eventForStorage)
    localEventsRef.current.push(event)
    setEvents((current) => [...current, event])
    setEventCount((count) => count + 1)
    if (shouldCaptureActionFrame(event, lastScreenshotAtRef.current, screenshotCountRef.current)) {
      lastScreenshotAtRef.current = event.elapsed_ms
      screenshotCountRef.current += 1
      const task = captureActionFrame(event)
      pendingScreenshotTasksRef.current.push(task)
      void task.catch(() => undefined).finally(() => {
        pendingScreenshotTasksRef.current = pendingScreenshotTasksRef.current.filter((item) => item !== task)
      })
    }
    const id = recordingIdRef.current
    if (id && queueRef.current.length >= 16) void flushEvents(id).catch(() => undefined)
  }, [captureActionFrame, flushEvents])

  const flushPendingInputEvents = useCallback(() => {
    if (inputDebounceTimerRef.current != null) {
      window.clearTimeout(inputDebounceTimerRef.current)
      inputDebounceTimerRef.current = null
    }
    const pending = [...pendingInputEventsRef.current.values()].sort((left, right) => left.sequence - right.sequence)
    pendingInputEventsRef.current.clear()
    for (const event of pending) recordEvent(event)
  }, [recordEvent])

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
    if (screenPreviewRef.current) {
      try { screenPreviewRef.current.pause() } catch { /* media teardown is best effort */ }
      screenPreviewRef.current.srcObject = null
      screenPreviewRef.current = null
    }
    mediaRecorderRef.current = null
    videoChunksRef.current = []
    videoBytesRef.current = 0
    return blob?.size ? blob : null
  }, [])

  const finishRecording = useCallback(
    async (id: string, stopNative: boolean) => {
      if (finishingRef.current) return
      finishingRef.current = true
      recordingActiveRef.current = false
      setBusy(true)
      const finishErrors: string[] = []
      try {
        if (stopNative) {
          try {
            await stopSkillRecording(id)
          } catch (stopError) {
            finishErrors.push(stopError instanceof Error ? stopError.message : String(stopError))
          }
        }
        flushPendingInputEvents()
        await Promise.allSettled(pendingScreenshotTasksRef.current)
        const video = await stopMediaCapture().catch((captureError: unknown) => {
          finishErrors.push(captureError instanceof Error ? captureError.message : String(captureError))
          return null
        })
        unlistenRef.current?.()
        unlistenRef.current = null
        await flushChainRef.current
        try {
          await flushEvents(id)
        } catch (flushError) {
          finishErrors.push(`Some recorded actions could not be saved: ${flushError instanceof Error ? flushError.message : String(flushError)}`)
        }
        try {
          await setSkillRecordingState(id, 'stop')
        } catch (stateError) {
          finishErrors.push(stateError instanceof Error ? stateError.message : String(stateError))
        }
        if (video) {
          pendingVideoRef.current = video
        }
        if (pendingVideoRef.current) {
          try {
            await uploadSkillRecordingVideo(id, pendingVideoRef.current)
            pendingVideoRef.current = null
            setVideoAvailable(true)
          } catch (uploadError) {
            finishErrors.push(`The local video could not be cached: ${uploadError instanceof Error ? uploadError.message : String(uploadError)}`)
          }
        }
        let reviewedEvents = localEventsRef.current
        try {
          const recording = await getSkillRecording(id)
          reviewedEvents = recording.events
          setVideoAvailable(Boolean(recording.video_artifacts?.length) || Boolean(pendingVideoRef.current))
        } catch (loadError) {
          finishErrors.push(`The saved action trace could not be reloaded: ${loadError instanceof Error ? loadError.message : String(loadError)}`)
        }
        reviewedEvents = reviewedEvents.map((event) => {
          const sourceSequence = event.source_sequence ?? event.sequence
          const value = reviewedInputValuesRef.current.get(sourceSequence)
          return event.kind === 'value_changed' && value !== undefined
            ? { ...event, value_state: 'captured' as const, value }
            : event
        })
        setEvents(reviewedEvents)
        setSelectedIds(reviewedEvents.map((event) => event.sequence))
        setRecordingStatus('stopped')
        setStage('review')
        setError(finishErrors.length ? `Recording stopped, but some items need attention: ${finishErrors.join(' | ')}` : null)
      } catch (finishError) {
        const message = finishError instanceof Error ? finishError.message : String(finishError)
        setEvents(localEventsRef.current)
        setSelectedIds(localEventsRef.current.map((event) => event.sequence))
        setRecordingStatus('stopped')
        setStage('review')
        setError(`Recording stopped, but review could not finish cleanly: ${message}`)
      } finally {
        finishingRef.current = false
        setBusy(false)
        await focusEvofluxAfterSkillRecording()
      }
    },
    [flushEvents, flushPendingInputEvents, stopMediaCapture],
  )

  useEffect(() => {
    mountedRef.current = true
    const pendingInputEvents = pendingInputEventsRef.current
    return () => {
      mountedRef.current = false
      const id = recordingIdRef.current
      unlistenRef.current?.()
      unlistenRef.current = null
      if (inputDebounceTimerRef.current != null) window.clearTimeout(inputDebounceTimerRef.current)
      inputDebounceTimerRef.current = null
      pendingInputEvents.clear()
      if (id && recordingActiveRef.current) {
        recordingActiveRef.current = false
        void (async () => {
          await stopSkillRecording(id).catch(() => undefined)
          await Promise.allSettled(pendingScreenshotTasksRef.current)
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
        const sharedSurface = selectedSurface === 'browser' ? 'a browser tab' : 'a single app window'
        throw new Error(
          `The picker selected ${sharedSurface} instead of the entire screen. Choose “Entire screen” to capture actions across apps.`,
        )
      }
      displayStreamRef.current = stream
      const screenPreview = document.createElement('video')
      screenPreview.muted = true
      screenPreview.autoplay = true
      screenPreview.playsInline = true
      screenPreview.srcObject = stream
      screenPreviewRef.current = screenPreview
      try { void Promise.resolve(screenPreview.play()).catch(() => undefined) } catch { /* frame capture may still work without autoplay */ }
      const session = await createSkillRecording()
      id = session.id
      if (!mountedRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        await deleteSkillRecording(session.id).catch(() => undefined)
        return
      }
      recordingIdRef.current = session.id
      queueRef.current = []
      localEventsRef.current = []
      reviewedInputValuesRef.current.clear()
      pendingInputEventsRef.current.clear()
      if (inputDebounceTimerRef.current != null) window.clearTimeout(inputDebounceTimerRef.current)
      inputDebounceTimerRef.current = null
      flushChainRef.current = Promise.resolve()
      lastScreenshotAtRef.current = -MIN_SCREENSHOT_INTERVAL_MS
      screenshotCountRef.current = 0
      pendingScreenshotTasksRef.current = []
      setVideoPlaybackError(false)
      const unlisten = await listenForSkillRecordingEvents(session.id, (event) => {
        if (event.kind === 'value_changed' && event.value_state === 'captured' && event.value != null) {
          const target = event.target
          const field = target?.automation_id || target?.label
          const key = field
            ? [event.window?.app, event.window?.title, field].filter(Boolean).join('|')
            : `sequence:${event.sequence}`
          pendingInputEventsRef.current.set(key, event)
          if (inputDebounceTimerRef.current != null) window.clearTimeout(inputDebounceTimerRef.current)
          inputDebounceTimerRef.current = window.setTimeout(flushPendingInputEvents, 600)
          return
        }
        flushPendingInputEvents()
        recordEvent(event)
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
      const mediaType = MediaRecorder.isTypeSupported('video/webm;codecs=vp8')
        ? 'video/webm;codecs=vp8'
        : MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
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
      if (targetLabel !== undefined && (event.target?.label || event.target?.name)) {
        redactions[event.target.label || event.target.name!] = targetLabel
      }
      const windowTitle = windowTitles[event.sequence]
      if (windowTitle !== undefined && event.window?.title) redactions[event.window.title] = windowTitle
    }
    const reviewed_input_values = events
      .filter((event) => selectedIds.includes(event.sequence) &&
        event.kind === 'value_changed' && event.value_state === 'captured' && event.value != null)
      .map((event) => ({ sequence: event.sequence, value: event.value! }))
    return { selected_event_ids: selectedIds, redactions, reviewed_input_values, goal: '' }
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
    const screenshotSequences = events
      .filter((event) => selectedIds.includes(event.sequence) && event.kind === 'screenshot' && event.screenshot)
      .map((event) => event.sequence)
      .slice(0, MAX_AUTO_SCREENSHOTS)
    stageSkillRecordingChatHandoff({
      recordingId,
      payload: preview.payload,
      ...(screenshotSequences.length ? { screenshotSequences } : {}),
    })
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
    setTargetLabels((current) => ({
      ...current,
      [sequence]: value === (event?.target?.label ?? event?.target?.name) ? '' : value,
    }))
    setPreview(null)
  }

  const changeWindowTitle = (sequence: number, value: string) => {
    const event = events.find((item) => item.sequence === sequence)
    setWindowTitles((current) => ({ ...current, [sequence]: value === event?.window?.title ? '' : value }))
    setPreview(null)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && (stage === 'recording' || busy)) return
        onOpenChange(nextOpen)
      }}
    >
      <DialogContent
        showCloseButton={stage === 'review' && !busy}
        overlayClassName="bg-black/50 backdrop-blur-[2px]"
        className="flex max-h-[min(88dvh,760px)] w-[calc(100vw-1.5rem)] max-w-2xl flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl"
      >
        <DialogHeader className="shrink-0 border-b border-(--color-border) px-5 py-4 pr-12">
          <DialogTitle className="flex items-center gap-2 text-base">
            {stage === 'recording' ? (
              <Radio className="size-4 text-(--color-error)" aria-hidden="true" />
            ) : stage === 'review' ? (
              <ShieldCheck className="size-4 text-(--color-success)" aria-hidden="true" />
            ) : (
              <MonitorPlay className="size-4 text-(--color-accent)" aria-hidden="true" />
            )}
            {stage === 'recording'
              ? 'Recording your desktop'
              : stage === 'review'
                ? 'Review recording'
                : 'Record a skill'}
          </DialogTitle>
          <DialogDescription className="text-xs leading-relaxed">
            {stage === 'select'
              ? 'Choose Entire screen when prompted. Stop whenever you are ready.'
              : stage === 'recording'
                ? 'The selected screen is being captured. Pause or stop whenever you are ready.'
                : 'Choose actions and screen frames to share. They stay on this device until you continue.'}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain p-4 sm:p-5">
          {error && (
            <SettingsCallout tone="error" icon={AlertCircle}>
              {error}
            </SettingsCallout>
          )}

      {stage === 'select' && (
        <div className="flex items-start gap-2 rounded-md bg-(--bg-key)/60 p-3 text-xs leading-relaxed text-(--color-text-muted)">
          <ShieldCheck size={15} className="mt-0.5 shrink-0 text-(--color-success)" aria-hidden="true" />
          <span>Video and captured actions stay on this device until you review them.</span>
        </div>
      )}

      {stage === 'recording' && (
        <>
          <SettingsCallout tone="warning" icon={Radio}>
            Recording the desktop · {eventCount} events. Clicks, scrolls, app/window names, field labels, and text from non-password fields are collected with up to 12 screen frames for local review. Nothing is sent to AI until you continue in chat and press Send. Video stays local and expires after one hour.
          </SettingsCallout>
          <SettingsGroup title="Recording controls" description="Pause while entering information you do not want in the demonstration, or stop to review the local recording.">
            <div className="flex flex-wrap items-center gap-2 p-4 sm:p-5">
              {recordingStatus === 'recording' ? (
                <Button variant="outline" onClick={() => void pauseRecording()} disabled={busy}><Pause aria-hidden="true" />Pause</Button>
              ) : (
                <Button variant="outline" onClick={() => void resumeRecording()} disabled={busy}><Play aria-hidden="true" />Resume</Button>
              )}
              <span className="text-xs text-(--color-text-muted)">Actions and video stay on this computer until you review and continue.</span>
            </div>
          </SettingsGroup>
          <div className="flex justify-end">
            <Button variant="destructive" onClick={() => recordingId && void finishRecording(recordingId, true)} disabled={busy}>
              {busy ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <CircleStop aria-hidden="true" />}
              Stop recording
            </Button>
          </div>
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
                  onError={() => setVideoPlaybackError(true)}
                />
              {videoPlaybackError && (
                <div role="status" className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-(--color-error)">
                  <span>The video could not be played here. Try downloading the WebM file or opening it in a media player.</span>
                  <a className="underline" href={skillRecordingVideoUrl(recordingId)} download="skill-demo-recording.webm">Download video</a>
                </div>
              )}
              </div>
            </SettingsGroup>
          )}
          <SettingsGroup title="Review captured actions" description="Remove steps that do not belong in the skill. Review typed values, replace private or one-off text with reusable variables, and check the screenshots before previewing.">
            <SkillRecordingTimeline
              recordingId={recordingId}
              events={events}
              selectedIds={selectedIds}
              variables={variables}
              targetLabels={targetLabels}
            windowTitles={windowTitles}
              onToggleEvent={toggleEvent}
              onVariableChange={changeVariable}
              onTargetLabelChange={changeTargetLabel}
            onWindowTitleChange={changeWindowTitle}
            />
          </SettingsGroup>
          {events.some((event) => event.kind === 'screenshot') && (
            <SettingsCallout tone="warning" icon={AlertCircle}>
              Review selected images and window titles before sending. Images can contain anything visible on screen; text redactions do not change image pixels.
            </SettingsCallout>
          )}
          <SettingsGroup title="Continue in chat" description="The trace and selected screen frames are attached locally. The model receives them only after you press Send.">
            <div className="space-y-3 p-4 sm:p-5">
              {preview ? (
                <>
                  <p className="text-sm font-medium">This event trace and selected screen frames will be attached to a new chat:</p>
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

        </div>

        {stage === 'select' && (
          <DialogFooter className="mx-0 mb-0 shrink-0 sm:flex-row sm:justify-between">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
            <Button onClick={() => void startRecording()} disabled={busy}>
              {busy ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Radio aria-hidden="true" />}
              Start recording
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}
