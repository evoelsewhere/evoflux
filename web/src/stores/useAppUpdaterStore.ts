import { create } from 'zustand'

import {
  checkForAppUpdates,
  downloadAppUpdate,
  restartToUpdate,
  type AppUpdateCheckResult,
  type AppUpdateProgress,
} from '@/lib/app-updater'
import { useToastStore } from '@/stores/useToastStore'

type AvailableUpdate = Extract<AppUpdateCheckResult, { status: 'available' }>

interface AppUpdaterStore {
  available: AvailableUpdate | null
  checking: boolean
  /** The update is downloading or being verified. EvoFlux keeps running. */
  downloading: boolean
  /**
   * Downloaded and verified. It installs when the user restarts from the
   * dialog, or the next time EvoFlux quits — whichever comes first.
   */
  ready: boolean
  /** EvoFlux is closing to install; there is no going back from here. */
  restarting: boolean
  /** Where the update has got to, or null before one starts. */
  progress: AppUpdateProgress | null
  /**
   * The dialog is out of the way, but the update is not cancelled.
   *
   * A download runs for minutes and the dialog used to refuse to close for
   * all of them. Putting it aside keeps the download going; the dialog comes
   * back when the update is ready to ask about the restart.
   */
  hidden: boolean
  error: string | null
  check: () => Promise<void>
  download: () => Promise<void>
  restart: () => Promise<void>
  dismiss: () => void
  handleResult: (result: AppUpdateCheckResult) => void
  handleProgress: (progress: AppUpdateProgress) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return 'The update operation failed.'
}

function showResult(result: AppUpdateCheckResult): AvailableUpdate | null {
  const pushToast = useToastStore.getState().push
  switch (result.status) {
    case 'available':
      return result
    case 'up_to_date':
      return null
    case 'error':
      pushToast({ tone: 'error', title: result.title, description: result.message }, 8_000)
      return null
    case 'busy':
    case 'unavailable':
      pushToast({ tone: 'info', title: result.title, description: result.message }, 8_000)
      return null
  }
}

export const useAppUpdaterStore = create<AppUpdaterStore>((set, get) => ({
  available: null,
  checking: false,
  downloading: false,
  ready: false,
  restarting: false,
  progress: null,
  hidden: false,
  error: null,

  handleResult: (result) => {
    const available = showResult(result)
    if (available) {
      // A download from earlier is picked up by the check itself, so a
      // relaunch never has to fetch the same update twice.
      const ready = available.ready === true
      set({
        available,
        ready,
        error: null,
        progress: ready ? { phase: 'ready' } : null,
        hidden: false,
      })
    }
  },

  // Progress is broadcast to every window, so it is also how a window that
  // did not start the download learns that one is under way.
  handleProgress: (progress) => {
    switch (progress.phase) {
      case 'ready':
        // Back into view to ask about the restart.
        set({ progress, downloading: false, ready: true, hidden: false })
        return
      case 'installing':
        // The app is about to close; it should not do that from behind a
        // dialog the user put away ten minutes ago.
        set({ progress, downloading: false, restarting: true, hidden: false })
        return
      default:
        set({ progress, downloading: true })
    }
  },

  check: async () => {
    if (get().checking || get().downloading || get().restarting) return
    set({ checking: true })
    try {
      get().handleResult(await checkForAppUpdates())
    } catch (error) {
      useToastStore.getState().push(
        {
          tone: 'error',
          title: 'Update check failed',
          description: errorMessage(error),
        },
        8_000,
      )
    } finally {
      set({ checking: false })
    }
  },

  download: async () => {
    const { available, downloading, ready, restarting } = get()
    if (!available || downloading || ready || restarting) return
    set({ downloading: true, error: null, progress: null })
    try {
      await downloadAppUpdate()
      set({ downloading: false, ready: true, progress: { phase: 'ready' }, hidden: false })
    } catch (error) {
      const message = errorMessage(error)
      set({ downloading: false, error: message, progress: null })
      useToastStore.getState().push(
        { tone: 'error', title: 'Update download failed', description: message },
        8_000,
      )
    }
  },

  restart: async () => {
    if (!get().ready || get().restarting) return
    set({ restarting: true, error: null, hidden: false })
    try {
      // On success EvoFlux exits and this never settles.
      await restartToUpdate()
    } catch (error) {
      const message = errorMessage(error)
      // Back to "Download": if the package is still on disk the shell finds
      // it again without fetching anything.
      set({ restarting: false, ready: false, progress: null, error: message })
      useToastStore.getState().push(
        { tone: 'error', title: 'Update installation failed', description: message },
        8_000,
      )
    }
  },

  dismiss: () => {
    const { downloading, ready, restarting } = get()
    // The install itself cannot be put aside: EvoFlux is seconds from closing.
    if (restarting) return
    // A download keeps going, and a ready update installs when EvoFlux quits.
    if (downloading || ready) {
      set({ hidden: true })
      return
    }
    // Closing the dialog before anything started declines the update until
    // the next check.
    set({ available: null, error: null, progress: null, hidden: false })
  },
}))
