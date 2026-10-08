import { useEffect, useMemo, useRef, useState } from 'react'
import { Copy, Download, Loader2, Mic, Plus, RefreshCw, Save, ShieldCheck, Trash2 } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { cancelLocalSttInstall, checkLocalSttRuntime, dismissLocalSttError, getLocalSttRuntime, installLocalSttRuntime, uninstallLocalSttRuntime, getVoiceSettings, listVoiceProviderModels, saveVoiceSettings, testVoiceProvider, type LocalSttRuntimeJob, type VoiceProviderProfile, type VoiceRouteEntry } from '@/api/client'
import { SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SelectControl } from '@/components/ui/select'
import { useToastStore } from '@/stores/useToastStore'
import { requestVoicePermission } from '@/lib/voice-permissions'

const ADAPTER_LABELS: Record<VoiceProviderProfile['adapter'], string> = {
  openai_compatible: 'OpenAI compatible (OpenAI, Groq, Whisper servers)',
  deepgram: 'Deepgram',
  azure_speech: 'Azure AI Speech',
  google_cloud: 'Google Cloud Speech-to-Text (ADC)',
  local_faster_whisper: 'Local Whisper (multilingual)',
}

const ENDPOINT_PLACEHOLDERS: Partial<Record<VoiceProviderProfile['adapter'], string>> = {
  openai_compatible: 'https://api.groq.com/openai/v1',
  deepgram: 'https://api.deepgram.com',
  azure_speech: 'https://{region}.api.cognitive.microsoft.com',
  google_cloud: 'https://speech.googleapis.com',
}

const blankProfile = (): VoiceProviderProfile => ({
  id: `stt-${Math.random().toString(36).slice(2, 8)}`,
  name: 'Speech provider',
  adapter: 'openai_compatible',
  base_url: '',
  models: [],
  locale: null,
  enabled: true,
})

function pairKey(pair: VoiceRouteEntry) { return `${pair.provider_id}:${pair.model_id}` }

function sameSavedProfile(saved: VoiceProviderProfile | undefined, current: VoiceProviderProfile): boolean {
  return !!saved && saved.name === current.name && saved.adapter === current.adapter &&
    saved.base_url === current.base_url && saved.locale === current.locale &&
    saved.enabled === current.enabled && JSON.stringify(saved.models) === JSON.stringify(current.models)
}

function endpointDestination(endpoint: string): string {
  try {
    const host = new URL(endpoint).hostname.toLowerCase()
    const privateEndpoint = host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || host.endsWith('.lan') || host.endsWith('.home.arpa') || host.endsWith('.ts.net') || host === '[::1]' || /^\[?(?:fc|fd)/.test(host) || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)/.test(host)
    return privateEndpoint ? 'Local / private network' : 'Hosted endpoint'
  } catch {
    return 'Endpoint not validated'
  }
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return 'size shown before download'
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`
}

function platformLabel(platform: string | null): string {
  if (!platform) return 'Unsupported platform'
  const labels: Record<string, string> = {
    'win32-x64': 'Windows x64',
    'darwin-x64': 'macOS Intel',
    'darwin-arm64': 'macOS Apple Silicon',
    'linux-x64': 'Linux x64',
  }
  return labels[platform] ?? platform
}

function runtimePhaseLabel(phase: LocalSttRuntimeJob['phase']): string {
  const labels: Record<LocalSttRuntimeJob['phase'], string> = {
    downloading_runtime: 'Downloading speech engine',
    downloading_model: 'Downloading Whisper model',
    verifying: 'Verifying downloaded files',
    extracting: 'Installing local model',
    checking: 'Checking model readiness',
    failed: 'Installation failed',
  }
  return labels[phase]
}

export function VoiceSettingsPage() {
  const client = useQueryClient()
  const pushToast = useToastStore((state) => state.push)
  const query = useQuery({ queryKey: ['voice-settings'], queryFn: getVoiceSettings })
  const runtimeQuery = useQuery({
    queryKey: ['local-stt-runtime'],
    queryFn: getLocalSttRuntime,
    refetchInterval: (current) => current.state.data?.job && current.state.data.job.phase !== 'failed' ? 800 : false,
  })
  const [profiles, setProfiles] = useState<VoiceProviderProfile[]>([])
  const [chain, setChain] = useState<VoiceRouteEntry[]>([])
  const [privateOnly, setPrivateOnly] = useState(false)
  const [allowHosted, setAllowHosted] = useState(false)
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [clearKeys, setClearKeys] = useState<string[]>([])
  const [modelCatalogs, setModelCatalogs] = useState<Record<string, string[]>>({})
  const [catalogSelections, setCatalogSelections] = useState<Record<string, string>>({})
  const [loadingCatalogId, setLoadingCatalogId] = useState<string | null>(null)
  const [newPair, setNewPair] = useState('')
  const [testRecordingId, setTestRecordingId] = useState<string | null>(null)
  const testRecorderRef = useRef<MediaRecorder | null>(null)
  const testStreamRef = useRef<MediaStream | null>(null)
  const testTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const testChunksRef = useRef<Blob[]>([])
  const testCancelledRef = useRef(false)

  useEffect(() => () => {
    testCancelledRef.current = true
    if (testTimerRef.current) clearTimeout(testTimerRef.current)
    if (testRecorderRef.current?.state === 'recording') testRecorderRef.current.stop()
    testStreamRef.current?.getTracks().forEach((track) => track.stop())
  }, [])

  useEffect(() => {
    if (!query.data) return
    setProfiles(query.data.providers)
    setChain(query.data.chain)
    setPrivateOnly(query.data.local_private_only)
    setAllowHosted(query.data.allow_hosted_fallback)
  }, [query.data])

  const pairs = useMemo(() => profiles.flatMap((profile) => (profile.adapter === 'local_faster_whisper' || profile.base_url.trim()) ? profile.models.map((model_id) => ({
    provider_id: profile.id, model_id,
  })) : []), [profiles])
  const save = useMutation({
    mutationFn: () => saveVoiceSettings({
      config: { providers: profiles, chain, allow_hosted_fallback: allowHosted, local_private_only: privateOnly },
      credentials: keys,
      clear_credentials: clearKeys,
    }),
    onSuccess: async (data) => {
      setKeys({})
      setClearKeys([])
      await client.setQueryData(['voice-settings'], data)
      pushToast({ tone: 'success', title: 'Voice settings saved' })
    },
    onError: (error) => pushToast({ tone: 'error', title: 'Could not save voice settings', description: error instanceof Error ? error.message : undefined }),
  })
  const runtimeAction = useMutation({
    mutationFn: async (action: 'install' | 'cancel' | 'check' | 'remove' | 'dismiss') => {
      if (action === 'install') await installLocalSttRuntime()
      else if (action === 'cancel') await cancelLocalSttInstall()
      else if (action === 'check') await checkLocalSttRuntime()
      else if (action === 'remove') await uninstallLocalSttRuntime()
      else await dismissLocalSttError()
      return getLocalSttRuntime()
    },
    onSuccess: (status) => { void client.setQueryData(['local-stt-runtime'], status) },
    onError: (error) => pushToast({ tone: 'error', title: 'Could not update Local STT', description: error instanceof Error ? error.message : undefined }),
  })

  const updateProfile = (id: string, patch: Partial<VoiceProviderProfile>) => {
    setProfiles((current) => current.map((profile) => profile.id === id ? { ...profile, ...patch } : profile))
    if ('base_url' in patch || 'adapter' in patch) {
      setModelCatalogs((current) => ({ ...current, [id]: [] }))
      setCatalogSelections((current) => ({ ...current, [id]: '' }))
    }
  }
  const removeProfile = (id: string) => {
    setProfiles((current) => current.filter((profile) => profile.id !== id))
    setChain((current) => current.filter((pair) => pair.provider_id !== id))
    setClearKeys((current) => [...new Set([...current, id])])
  }
  const duplicateProfile = (profile: VoiceProviderProfile) => {
    const occupied = new Set(profiles.map((item) => item.id))
    const root = profile.id.slice(0, 42)
    const base = `${root}-copy`
    let id = base
    let suffix = 2
    while (occupied.has(id)) id = `${root}-copy-${suffix++}`
    const duplicate = {
      ...profile,
      id,
      name: `${profile.name} copy`,
      credential_configured: false,
      health: null,
    }
    setProfiles((current) => [...current, duplicate])
    setKeys((current) => ({ ...current, [id]: '' }))
    setClearKeys((current) => current.filter((item) => item !== id))
  }

  const loadModels = async (profile: VoiceProviderProfile) => {
    const saved = query.data?.providers.find((item) => item.id === profile.id)
    if (!sameSavedProfile(saved, profile) || keys[profile.id]?.trim() || clearKeys.includes(profile.id)) {
      pushToast({ tone: 'error', title: 'Save provider settings first', description: 'Save the endpoint and API key before loading its model catalog.' })
      return
    }
    setLoadingCatalogId(profile.id)
    try {
      const result = await listVoiceProviderModels(profile.id)
      setModelCatalogs((current) => ({ ...current, [profile.id]: result.models }))
      setCatalogSelections((current) => ({ ...current, [profile.id]: result.models[0] ?? '' }))
      if (result.models.length === 0) pushToast({ tone: 'info', title: 'No models returned', description: 'This endpoint did not return a model catalog. You can enter a model ID manually.' })
    } catch (error) {
      pushToast({ tone: 'error', title: 'Could not load models', description: error instanceof Error ? error.message : 'Check the endpoint and saved credential.' })
    } finally {
      setLoadingCatalogId(null)
    }
  }

  const addCatalogModel = (profile: VoiceProviderProfile) => {
    const model = catalogSelections[profile.id]
    if (model && !profile.models.includes(model)) updateProfile(profile.id, { models: [...profile.models, model] })
  }

  const addLocalProvider = () => {
    const status = runtimeQuery.data
    if (!status?.healthy || profiles.some((profile) => profile.adapter === 'local_faster_whisper')) return
    setProfiles((current) => [...current, {
      id: 'local-whisper',
      name: 'Local Whisper small',
      adapter: 'local_faster_whisper',
      base_url: '',
      models: [status.model_id],
      locale: null,
      enabled: true,
    }])
  }
  const addPair = () => {
    const pair = pairs.find((item) => pairKey(item) === newPair)
    if (pair && !chain.some((item) => pairKey(item) === newPair)) setChain((current) => [...current, pair])
    setNewPair('')
  }
  const beginProviderTest = async (profile: VoiceProviderProfile) => {
    if (testRecordingId) {
      if (testTimerRef.current) clearTimeout(testTimerRef.current)
      if (testRecorderRef.current) testRecorderRef.current.stop()
      else {
        testCancelledRef.current = true
        setTestRecordingId(null)
      }
      return
    }
    const modelId = profile.models[0]
    if (!modelId) return
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      pushToast({ tone: 'error', title: 'Microphone unavailable', description: 'This browser does not support microphone recording.' })
      return
    }
    try {
      testCancelledRef.current = false
      setTestRecordingId(profile.id)
      await requestVoicePermission()
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (testCancelledRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      testStreamRef.current = stream
      const type = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find((candidate) => MediaRecorder.isTypeSupported(candidate))
      const recorder = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream)
      testChunksRef.current = []
      testCancelledRef.current = false
      testRecorderRef.current = recorder
      recorder.ondataavailable = (event) => { if (event.data.size > 0) testChunksRef.current.push(event.data) }
      recorder.onstop = async () => {
        testStreamRef.current?.getTracks().forEach((track) => track.stop())
        testStreamRef.current = null
        testRecorderRef.current = null
        setTestRecordingId(null)
        const chunks = testChunksRef.current
        testChunksRef.current = []
        if (testCancelledRef.current || !chunks.length) return
        try {
          const mime = recorder.mimeType || chunks[0]?.type || 'audio/webm'
          const extension = mime.includes('ogg') ? 'ogg' : mime.includes('mp4') ? 'm4a' : 'webm'
          const result = await testVoiceProvider(profile.id, modelId, new File(chunks, `provider-test.${extension}`, { type: mime }))
          pushToast({ tone: 'success', title: 'Provider test succeeded', description: `${result.provider_id} · ${result.model_id}` })
        } catch (error) {
          pushToast({ tone: 'error', title: 'Provider test failed', description: error instanceof Error ? error.message : 'Check provider settings and try again.' })
        }
      }
      recorder.start()
      testTimerRef.current = setTimeout(() => recorder.stop(), 4_000)
    } catch (error) {
      testStreamRef.current?.getTracks().forEach((track) => track.stop())
      testStreamRef.current = null
      setTestRecordingId(null)
      pushToast({ tone: 'error', title: 'Microphone unavailable', description: error instanceof Error ? error.message : 'Allow microphone access to record a provider test sample.' })
    }
  }

  if (query.isLoading) return <SettingsPage icon={Mic} title="Voice input" lede="Configure speech-to-text providers and fallback order."><p className="text-sm text-(--color-text-muted)">Loading voice settings…</p></SettingsPage>

  return (
    <SettingsPage
      icon={Mic}
      title="Voice input"
      lede="Configure speech-to-text providers for push-to-talk. Recordings are sent only to the providers in your ordered chain; transcripts stay in the composer for you to review."
      actions={<Button onClick={() => save.mutate()} disabled={save.isPending}><Save size={15} /> Save changes</Button>}
      size="wide"
    >
      <SettingsGroup title="Optional local model" description="Download once to transcribe on the EvoFlux host. Remote and custom providers continue to work without this download.">
        <div className="space-y-3 p-4">
          <div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-(--color-text)">Whisper small · English, Vietnamese and Japanese</p>
              <p className="mt-1 text-xs leading-relaxed text-(--color-text-muted)">Download once to transcribe on the EvoFlux host. Audio from a remote phone is sent to that host. After installation, Whisper transcribes offline.</p>
              <p className="mt-1 text-xs text-(--color-text-subtle)">{runtimeQuery.isLoading ? 'Checking this device' : runtimeQuery.isError ? 'Download status could not be checked' : runtimeQuery.data ? platformLabel(runtimeQuery.data.platform) : 'Checking this device'}{runtimeQuery.data && ` · ${runtimeQuery.data.available ? `download ${formatBytes(runtimeQuery.data.download_bytes)}` : 'download not published for this platform'}`}{runtimeQuery.data?.install_bytes ? ` · installed ${formatBytes(runtimeQuery.data.install_bytes)}` : ''}</p>
            </div>
            {runtimeQuery.isError && <Button variant="outline" size="sm" onClick={() => void runtimeQuery.refetch()} disabled={runtimeQuery.isFetching}><RefreshCw size={14} /> Retry status</Button>}
            {runtimeQuery.data?.healthy && !profiles.some((profile) => profile.adapter === 'local_faster_whisper') && <Button variant="outline" size="sm" onClick={addLocalProvider}>Add provider</Button>}
            {runtimeQuery.data?.state === 'installing' && <Button variant="outline" size="sm" onClick={() => runtimeAction.mutate('cancel')} disabled={runtimeAction.isPending}>Cancel</Button>}
            {runtimeQuery.data?.state === 'failed' && <>
              <Button variant="outline" size="sm" onClick={() => runtimeAction.mutate('install')} disabled={runtimeAction.isPending}><RefreshCw size={14} /> Retry</Button>
              <Button variant="ghost" size="sm" onClick={() => runtimeAction.mutate('dismiss')} disabled={runtimeAction.isPending}>Dismiss</Button>
            </>}
            {runtimeQuery.data?.state === 'ready' && <>
              {runtimeQuery.data.available && runtimeQuery.data.model_version !== runtimeQuery.data.installed_model_version && <Button variant="outline" size="sm" onClick={() => runtimeAction.mutate('install')} disabled={runtimeAction.isPending}><Download size={14} /> Update</Button>}
              <Button variant="outline" size="sm" onClick={() => runtimeAction.mutate('check')} disabled={runtimeAction.isPending}><RefreshCw size={14} /> Check</Button>
              <Button variant="ghost" size="sm" onClick={() => runtimeAction.mutate('remove')} disabled={runtimeAction.isPending}><Trash2 size={14} /> Remove</Button>
            </>}
            {runtimeQuery.data?.available && ['not_installed', 'needs_repair'].includes(runtimeQuery.data.state) && <Button size="sm" onClick={() => runtimeAction.mutate('install')} disabled={runtimeAction.isPending}><Download size={14} /> {runtimeQuery.data.state === 'needs_repair' ? 'Repair' : 'Download to enable'}</Button>}
          </div>
          {runtimeQuery.data?.job && runtimeQuery.data.job.phase !== 'failed' && <div role="status" aria-live="polite" className="space-y-1.5">
            <div className="flex items-center gap-2 text-xs text-(--color-text-muted)"><Loader2 size={13} className="animate-spin" />{runtimePhaseLabel(runtimeQuery.data.job.phase)}<span className="ml-auto tabular-nums">{Math.min(100, Math.round(runtimeQuery.data.job.bytes_done * 100 / Math.max(1, runtimeQuery.data.job.bytes_total)))}% · {formatBytes(runtimeQuery.data.job.bytes_done)} / {formatBytes(runtimeQuery.data.job.bytes_total)}</span></div>
            <div className="h-1.5 overflow-hidden rounded-full bg-(--bg-key)" role="progressbar" aria-label="Local STT download progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, Math.round(runtimeQuery.data.job.bytes_done * 100 / Math.max(1, runtimeQuery.data.job.bytes_total)))}><div className="h-full bg-(--color-accent)" style={{ width: `${Math.min(100, runtimeQuery.data.job.bytes_done * 100 / Math.max(1, runtimeQuery.data.job.bytes_total))}%` }} /></div>
          </div>}
          {runtimeQuery.data?.job?.phase === 'failed' && <p role="alert" className="text-xs text-(--color-error)">{runtimeQuery.data.job.error || 'Local STT installation failed.'}</p>}
          {runtimeQuery.data?.state === 'unavailable' && <p className="text-xs text-(--color-text-subtle)">Whisper downloads are not published for this app version yet. Other speech providers still work.</p>}
          {runtimeQuery.data?.state === 'ready' && <p className="text-xs text-(--color-text-subtle)">Installed and ready · runtime {runtimeQuery.data.installed_runtime_version} · model {runtimeQuery.data.installed_model_version}</p>}
        </div>
      </SettingsGroup>
      <SettingsGroup title="Speech providers" description="Choose where recordings are transcribed. Credentials stay on the EvoFlux host." actions={<Button variant="outline" size="sm" onClick={() => setProfiles((current) => [...current, blankProfile()])}><Plus size={14} /> Add provider</Button>}>
        <div className="space-y-3">
          {profiles.map((profile) => (
            <article key={profile.id} className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
              <div className="grid gap-3 md:grid-cols-2">
                <label className="space-y-1 text-xs text-(--color-text-muted)">Profile name<Input value={profile.name} onChange={(e) => updateProfile(profile.id, { name: e.target.value })} /></label>
                <label className="space-y-1 text-xs text-(--color-text-muted)">Adapter<SelectControl className="w-full" value={profile.adapter} disabled={profile.adapter === 'local_faster_whisper'} onValueChange={(value) => updateProfile(profile.id, { adapter: value as VoiceProviderProfile['adapter'] })} options={Object.entries(ADAPTER_LABELS).filter(([id]) => id !== 'local_faster_whisper' || profile.adapter === 'local_faster_whisper').map(([value, label]) => ({ value, label }))} /></label>
                {profile.adapter !== 'local_faster_whisper' && <label className="space-y-1 text-xs text-(--color-text-muted)">Endpoint<Input value={profile.base_url} onChange={(e) => updateProfile(profile.id, { base_url: e.target.value })} placeholder={ENDPOINT_PLACEHOLDERS[profile.adapter] ?? 'https://api.example.com/v1'} /></label>}
                <div className="space-y-1 text-xs text-(--color-text-muted)">
                  <label htmlFor={`voice-models-${profile.id}`}>Model IDs (comma separated)</label>
                  <div className="flex gap-2">
                    <Input id={`voice-models-${profile.id}`} value={profile.models.join(', ')} onChange={(e) => updateProfile(profile.id, { models: e.target.value.split(',').map((value) => value.trim()).filter(Boolean) })} placeholder="whisper-large-v3-turbo" />
                    {profile.adapter === 'openai_compatible' && <Button variant="outline" size="sm" onClick={() => void loadModels(profile)} disabled={!profile.base_url.trim() || !sameSavedProfile(query.data?.providers.find((item) => item.id === profile.id), profile) || !!keys[profile.id]?.trim() || clearKeys.includes(profile.id) || loadingCatalogId === profile.id} title={!profile.base_url.trim() ? 'Configure an endpoint first.' : !sameSavedProfile(query.data?.providers.find((item) => item.id === profile.id), profile) || !!keys[profile.id]?.trim() ? 'Save this provider before loading models.' : undefined}>{loadingCatalogId === profile.id ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}{loadingCatalogId === profile.id ? 'Loading' : 'Load models'}</Button>}
                  </div>
                  {(modelCatalogs[profile.id]?.length ?? 0) > 0 && <div className="flex gap-2 pt-1">
                    <SelectControl className="min-w-0 flex-1" ariaLabel={`Available models for ${profile.name}`} value={catalogSelections[profile.id] ?? ''} onValueChange={(value) => setCatalogSelections((current) => ({ ...current, [profile.id]: value }))} placeholder="Choose a model" options={modelCatalogs[profile.id].map((model) => ({ value: model, label: model }))} />
                    <Button variant="outline" size="sm" onClick={() => addCatalogModel(profile)} disabled={!catalogSelections[profile.id] || profile.models.includes(catalogSelections[profile.id])}><Plus size={14} /> Add model</Button>
                  </div>}
                </div>
                {profile.adapter !== 'google_cloud' && profile.adapter !== 'local_faster_whisper' && <label className="space-y-1 text-xs text-(--color-text-muted)">API key {profile.credential_configured ? '(saved; leave blank to keep)' : ''}<Input type="password" autoComplete="new-password" value={keys[profile.id] ?? ''} onChange={(e) => setKeys((current) => ({ ...current, [profile.id]: e.target.value }))} placeholder={profile.credential_configured ? 'Saved securely' : 'Enter provider key'} /></label>}
                <details className="md:col-span-2">
                  <summary className="cursor-pointer text-xs text-(--color-text-muted)">Advanced settings</summary>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <label className="space-y-1 text-xs text-(--color-text-muted)">Profile ID<Input value={profile.id} readOnly title="Profile IDs stay stable so saved credentials and fallback references remain attached." /></label>
                    <label className="space-y-1 text-xs text-(--color-text-muted)">Default language / locale<Input value={profile.locale ?? ''} onChange={(e) => updateProfile(profile.id, { locale: e.target.value || null })} placeholder="en-US" /></label>
                  </div>
                </details>
              </div>
              <p className="text-xs text-(--color-text-subtle)">Record test sample captures up to four seconds and sends it only to this endpoint. Provider service terms apply to hosted endpoints.</p>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-(--color-border-subtle) pt-3">
                <label className="flex items-center gap-2 text-xs text-(--color-text-muted)"><input type="checkbox" checked={profile.enabled} onChange={(e) => updateProfile(profile.id, { enabled: e.target.checked })} /> Enabled</label>
                <span className="text-xs text-(--color-text-subtle)">{profile.adapter === 'local_faster_whisper' ? 'Runs on the EvoFlux host · no endpoint or API key' : !profile.base_url.trim() ? 'Draft profile · configure an endpoint to load models or use it for voice input.' : `${endpointDestination(profile.base_url)} · ${profile.adapter === 'google_cloud' ? 'Uses backend Application Default Credentials.' : profile.credential_configured ? 'Credential configured.' : 'No credential saved.'}`}</span>
                {profile.health && <span className={profile.health.status === 'needs_attention' ? 'text-xs text-(--color-error)' : 'text-xs text-(--color-text-muted)'}>{profile.health.status === 'needs_attention' ? 'Needs attention' : profile.health.status === 'healthy' ? 'Last check succeeded' : `Last issue: ${profile.health.last_failure ?? 'provider error'}`}</span>}
                {profile.credential_configured && <button type="button" className="text-xs text-(--color-error)" onClick={() => { setClearKeys((current) => [...new Set([...current, profile.id])]); setKeys((current) => ({ ...current, [profile.id]: '' })) }}>Clear saved key</button>}
                <Button variant="ghost" size="sm" onClick={() => duplicateProfile(profile)} aria-label={`Duplicate ${profile.name}`}><Copy size={14} /> Duplicate</Button>
                <Button variant="outline" size="sm" disabled={!profile.enabled || (profile.adapter !== 'local_faster_whisper' && !profile.base_url.trim()) || profile.models.length === 0 || !sameSavedProfile(query.data?.providers.find((item) => item.id === profile.id), profile) || !!keys[profile.id]?.trim() || clearKeys.includes(profile.id) || (!!testRecordingId && testRecordingId !== profile.id)} onClick={() => void beginProviderTest(profile)} title={!profile.base_url.trim() || !sameSavedProfile(query.data?.providers.find((item) => item.id === profile.id), profile) || !!keys[profile.id]?.trim() || clearKeys.includes(profile.id) ? 'Configure and save this provider profile before recording a test sample.' : undefined}>{testRecordingId === profile.id ? 'Stop 4-second test sample' : 'Record test sample'}</Button>
                <Button variant="ghost" size="sm" onClick={() => removeProfile(profile.id)} aria-label={`Remove ${profile.name}`}><Trash2 size={14} /></Button>
              </div>
            </article>
          ))}
          {profiles.length === 0 && <p className="rounded-xl border border-dashed border-(--color-border) p-5 text-sm text-(--color-text-muted)">No speech providers yet. Add one to enable the microphone in chat.</p>}
        </div>
      </SettingsGroup>

      <SettingsGroup title="Provider order and recording privacy" description="EvoFlux tries the first service, then the backups in order if it fails.">
        <div className="space-y-3 p-4">
          <label className="block space-y-1 text-xs text-(--color-text-muted)">First provider and model<SelectControl className="w-full" value={chain[0] ? pairKey(chain[0]) : ''} onValueChange={(value) => { const pair = pairs.find((item) => pairKey(item) === value); if (pair) setChain((current) => [pair, ...current.filter((item) => pairKey(item) !== value)]) }} placeholder="Choose the first provider" options={pairs.map((pair) => ({ value: pairKey(pair), label: `${profiles.find((p) => p.id === pair.provider_id)?.name} · ${pair.model_id}` }))} /></label>
          <div className="space-y-2">{chain.slice(1).map((pair, index) => <div key={pairKey(pair)} className="flex items-center gap-2 rounded-lg border border-(--color-border-subtle) px-3 py-2 text-sm"><span className="min-w-0 flex-1 truncate">Fallback {index + 1}: {profiles.find((p) => p.id === pair.provider_id)?.name} · {pair.model_id}</span><button type="button" disabled={index === 0} onClick={() => setChain((current) => { const copy = [...current]; const i = index + 1; [copy[i - 1], copy[i]] = [copy[i], copy[i - 1]]; return copy })} className="text-xs text-(--color-text-muted) disabled:opacity-30">Move up</button><button type="button" onClick={() => setChain((current) => current.filter((item) => pairKey(item) !== pairKey(pair)))} className="text-xs text-(--color-error)">Remove</button></div>)}</div>
          <div className="flex gap-2"><SelectControl className="min-w-0 flex-1" value={newPair} onValueChange={setNewPair} placeholder="Add fallback…" options={pairs.filter((pair) => !chain.some((item) => pairKey(item) === pairKey(pair))).map((pair) => ({ value: pairKey(pair), label: `${profiles.find((p) => p.id === pair.provider_id)?.name} · ${pair.model_id}` }))} /><Button variant="outline" size="sm" onClick={addPair} disabled={!newPair}><Plus size={14} /> Add fallback</Button></div>
          <label className="flex items-start gap-2 rounded-lg bg-(--bg-key) p-3 text-sm"><input type="checkbox" className="mt-1" checked={allowHosted} onChange={(e) => setAllowHosted(e.target.checked)} /><span><span className="font-medium text-(--color-text)">Allow online speech services to receive recordings</span><span className="mt-1 block text-xs leading-relaxed text-(--color-text-muted)">Off by default. Your private or local providers can still receive audio.</span></span></label>
          <label className="flex items-start gap-2 rounded-lg bg-(--bg-key) p-3 text-sm"><input type="checkbox" className="mt-1" checked={privateOnly} onChange={(e) => setPrivateOnly(e.target.checked)} /><span><span className="flex items-center gap-1.5 font-medium text-(--color-text)"><ShieldCheck size={14} /> Use local or private-network providers only</span><span className="mt-1 block text-xs leading-relaxed text-(--color-text-muted)">Online providers are skipped, including in your backup list. EvoFlux will not add another service automatically.</span></span></label>
          <p className="text-xs leading-relaxed text-(--color-text-subtle)">Online services may process and retain audio under their own terms. EvoFlux does not save recordings or transcripts.</p>
        </div>
      </SettingsGroup>
      {query.data?.providers.some((profile) => profile.adapter === 'google_cloud') && <p className="flex items-start gap-2 text-xs text-(--color-text-muted)"><ShieldCheck size={15} className="mt-0.5 shrink-0" /> Google Cloud Speech uses Application Default Credentials configured for the EvoFlux backend host; no service credential is sent to your browser.</p>}
    </SettingsPage>
  )
}
