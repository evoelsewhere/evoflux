import { STORAGE_KEYS } from '@/lib/storage-keys'

export interface NotificationSound {
  id: string
  name: string
  builtIn: boolean
  selected: boolean
  file?: Blob
}

interface StoredSound {
  id: string
  name: string
  file: Blob
}

const DATABASE = 'evoflux-notification-sounds'
const STORE = 'sounds'
const BUILTIN_ID = 'builtin-default'
const SELECTED_KEY = STORAGE_KEYS.desktopNotifications.selectedSound
const MAX_BYTES = 5 * 1024 * 1024
const MAX_DURATION_SECONDS = 15
const ACCEPTED = new Set(['audio/wav', 'audio/x-wav', 'audio/wave', 'audio/mpeg', 'audio/mp3', 'audio/ogg', 'audio/vorbis'])

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') return reject(new Error('Local sound storage is unavailable.'))
    const request = indexedDB.open(DATABASE, 1)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE, { keyPath: 'id' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Could not open local sound storage.'))
  })
}

async function withStore<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDatabase()
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = run(db.transaction(STORE, mode).objectStore(STORE))
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error ?? new Error('Local sound storage operation failed.'))
    })
  } finally {
    db.close()
  }
}

function durationOf(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const audio = new Audio()
    audio.preload = 'metadata'
    audio.onloadedmetadata = () => {
      URL.revokeObjectURL(url)
      if (!Number.isFinite(audio.duration)) reject(new Error('Could not read the audio duration.'))
      else resolve(audio.duration)
    }
    audio.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('This audio file could not be decoded.'))
    }
    audio.src = url
  })
}

export async function listNotificationSounds(): Promise<NotificationSound[]> {
  const stored = await withStore<StoredSound[]>('readonly', (store) => store.getAll())
  const selected = localStorage.getItem(SELECTED_KEY) || BUILTIN_ID
  return [
    { id: BUILTIN_ID, name: 'Default EvoFlux sound', builtIn: true, selected: selected === BUILTIN_ID },
    ...stored.map((sound) => ({ ...sound, builtIn: false, selected: selected === sound.id })),
  ]
}

export async function importNotificationSound(file: File, name = file.name.replace(/\.[^.]+$/, '')): Promise<void> {
  if (file.size > MAX_BYTES) throw new Error('Audio files must be 5 MiB or smaller.')
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (!['wav', 'mp3', 'ogg'].includes(extension ?? '')) {
    throw new Error('Choose a WAV, MP3 or OGG audio file.')
  }
  if (file.type && !ACCEPTED.has(file.type)) {
    throw new Error('Choose a WAV, MP3 or OGG audio file.')
  }
  const header = new Uint8Array(await file.slice(0, 12).arrayBuffer())
  const signature = String.fromCharCode(...header)
  const formatMatches = extension === 'wav'
    ? signature.startsWith('RIFF') && signature.slice(8, 12) === 'WAVE'
    : extension === 'ogg'
      ? signature.startsWith('OggS')
      : signature.startsWith('ID3') || (header[0] === 0xff && (header[1] & 0xe0) === 0xe0)
  if (!formatMatches) throw new Error('The file contents do not match a supported WAV, MP3 or OGG format.')
  if (await durationOf(file) > MAX_DURATION_SECONDS) throw new Error('Audio must be 15 seconds or shorter.')
  const id = crypto.randomUUID()
  await withStore('readwrite', (store) => store.add({ id, name: name.trim().slice(0, 80) || 'Custom sound', file }))
  localStorage.setItem(SELECTED_KEY, id)
}

export async function renameNotificationSound(id: string, name: string): Promise<void> {
  if (!name.trim()) throw new Error('Sound name cannot be empty.')
  const sound = await withStore<StoredSound | undefined>('readonly', (store) => store.get(id))
  if (!sound) throw new Error('Sound not found.')
  await withStore('readwrite', (store) => store.put({ ...sound, name: name.trim().slice(0, 80) }))
}

export async function selectNotificationSound(id: string): Promise<void> {
  if (id !== BUILTIN_ID && !(await withStore<StoredSound | undefined>('readonly', (store) => store.get(id)))) {
    throw new Error('Sound not found.')
  }
  localStorage.setItem(SELECTED_KEY, id)
}

export async function deleteNotificationSound(id: string): Promise<void> {
  if (id === BUILTIN_ID) throw new Error('The built-in sound cannot be deleted.')
  if (localStorage.getItem(SELECTED_KEY) === id) localStorage.setItem(SELECTED_KEY, BUILTIN_ID)
  await withStore('readwrite', (store) => store.delete(id))
}

export async function getSelectedNotificationSound(): Promise<Blob | null> {
  const selected = localStorage.getItem(SELECTED_KEY) || BUILTIN_ID
  if (selected === BUILTIN_ID) return null
  const sound = await withStore<StoredSound | undefined>('readonly', (store) => store.get(selected))
  return sound?.file ?? null
}
