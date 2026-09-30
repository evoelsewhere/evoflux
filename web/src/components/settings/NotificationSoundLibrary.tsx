import { useEffect, useState } from 'react'
import { AudioLines, Check, Pencil, Play, Plus, Trash2 } from 'lucide-react'

import {
  deleteNotificationSound,
  importNotificationSound,
  listNotificationSounds,
  renameNotificationSound,
  selectNotificationSound,
  type NotificationSound,
} from '@/lib/notification-sound-library'
import { Button } from '@/components/ui/button'
import { translateText } from '@/i18n'

export function NotificationSoundLibrary() {
  const [sounds, setSounds] = useState<NotificationSound[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftName, setDraftName] = useState('')

  const refresh = async () => {
    try {
      setSounds(await listNotificationSounds())
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load notification sounds.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [])

  const run = async (action: () => Promise<void>): Promise<boolean> => {
    try {
      await action()
      await refresh()
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The sound could not be updated.')
      return false
    }
  }

  const preview = async (sound: NotificationSound) => {
    try {
      const source = sound.file ? URL.createObjectURL(sound.file) : '/notification.wav'
      const audio = new Audio(source)
      audio.onended = () => { if (sound.file) URL.revokeObjectURL(source) }
      audio.onerror = () => { if (sound.file) URL.revokeObjectURL(source) }
      await audio.play()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'This sound could not be played.')
    }
  }

  const handleFile = async (file?: File) => {
    if (!file) return
    await run(() => importNotificationSound(file))
  }

  const beginRename = (sound: NotificationSound) => {
    setEditingId(sound.id)
    setDraftName(sound.name)
  }

  const saveRename = async (soundId: string) => {
    const saved = await run(() => renameNotificationSound(soundId, draftName))
    if (saved) setEditingId(null)
  }

  return (
    <div className="overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card) shadow-sm">
      <div className="flex flex-col gap-3 border-b border-(--color-border) p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium">{translateText('Notification sound')}</p>
          <p className="max-w-2xl text-sm leading-5 text-muted-foreground">{translateText('Sounds stay on this device. WAV, MP3 or OGG, up to 5 MiB and 15 seconds.')}</p>
        </div>
        <label className="inline-flex min-h-10 shrink-0 cursor-pointer items-center gap-2 self-start rounded-md border px-3 text-sm hover:bg-muted sm:self-center">
          <Plus size={14} aria-hidden="true" /> {translateText('Add sound')}
          <input
            className="sr-only"
            type="file"
            accept=".wav,.mp3,.ogg,audio/wav,audio/mpeg,audio/ogg"
            aria-label={translateText('Add notification sound')}
            onChange={(event) => { void handleFile(event.currentTarget.files?.[0]); event.currentTarget.value = '' }}
          />
        </label>
      </div>
      {error && <p role="alert" className="border-b border-(--color-border) px-4 py-3 text-sm text-destructive sm:px-5">{error}</p>}
      {loading ? <p className="px-4 py-4 text-sm text-muted-foreground sm:px-5">Loading sounds…</p> : (
        <ul className="divide-y divide-(--color-border)">
          {sounds.map((sound) => (
            <li
              key={sound.id}
              className={`px-4 py-4 transition-colors sm:px-5 ${sound.selected
                ? 'border-l-2 border-l-primary bg-primary/10 pl-[calc(1rem-2px)] sm:pl-[calc(1.25rem-2px)]'
                : ''
              }`}
              aria-current={sound.selected ? 'true' : undefined}
            >
              <div className="flex flex-col gap-3 md:flex-row md:items-center">
                <span className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${sound.selected
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-(--bg-key) text-(--color-text-muted)'
                }`} aria-hidden="true">
                  <AudioLines size={16} />
                </span>
                <div className="min-w-0 flex-1">
                  {editingId === sound.id ? (
                    <form
                      className="flex flex-wrap items-center gap-2"
                      onSubmit={(event) => { event.preventDefault(); void saveRename(sound.id) }}
                    >
                      <input
                        type="text"
                        className="h-9 min-w-32 flex-1 rounded-md border border-primary/45 bg-(--bg-input) px-2.5 text-sm text-(--color-text) outline-none focus:ring-2 focus:ring-(--focus-ring)/30"
                        value={draftName}
                        maxLength={80}
                        aria-label={translateText('Sound name')}
                        onChange={(event) => setDraftName(event.currentTarget.value)}
                      />
                      <Button type="submit" size="sm" disabled={!draftName.trim()}>
                        <Check aria-hidden="true" /> {translateText('Save')}
                      </Button>
                      <Button type="button" size="sm" variant="outline" onClick={() => setEditingId(null)}>
                        {translateText('Cancel')}
                      </Button>
                    </form>
                  ) : (
                    <>
                      <p className="truncate text-sm font-medium text-(--color-text)">{sound.name}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-(--color-text-muted)">
                        <span>{sound.builtIn ? translateText('Built-in') : translateText('Custom sound')}</span>
                        {sound.selected && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-primary px-2 py-0.5 font-medium text-primary-foreground">
                            <Check size={12} aria-hidden="true" /> {translateText('In use')}
                          </span>
                        )}
                      </div>
                    </>
                  )}
                </div>
                {editingId !== sound.id && (
                  <div className="flex flex-wrap items-center gap-1.5 md:ml-auto md:justify-end">
                    {sound.selected ? (
                      <Button size="sm" disabled aria-label={`${translateText('In use')}: ${sound.name}`}>
                        <Check aria-hidden="true" /> {translateText('In use')}
                      </Button>
                    ) : (
                      <Button size="sm" className="bg-primary text-primary-foreground hover:opacity-90" onClick={() => void run(() => selectNotificationSound(sound.id))}>
                        <Check aria-hidden="true" /> {translateText('Use sound')}
                      </Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => void preview(sound)}>
                      <Play aria-hidden="true" /> {translateText('Preview')}
                    </Button>
                    {!sound.builtIn && <>
                      <Button size="sm" variant="outline" onClick={() => beginRename(sound)}>
                        <Pencil aria-hidden="true" /> {translateText('Rename')}
                      </Button>
                      <Button size="sm" variant="outline" className="text-(--color-error) hover:border-(--color-error)/35 hover:bg-(--color-error-subtle)" onClick={() => void run(() => deleteNotificationSound(sound.id))}>
                        <Trash2 aria-hidden="true" /> {translateText('Delete')}
                      </Button>
                    </>}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
