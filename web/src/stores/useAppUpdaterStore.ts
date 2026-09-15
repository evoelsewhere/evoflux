import { create } from 'zustand'

import {
  checkForAppUpdates,
  installAppUpdate,
  type AppUpdateCheckResult,
  type AppUpdateProgress,
} from '@/lib/app-updater'
import { useToastStore } from '@/stores/useToastStore'

type AvailableUpdate = Extract<AppUpdateCheckResult, { status: 'available' }>

interface AppUpdaterStore {
  available: AvailableUpdate | null
  checking: boolean
  installing: boolean
  /** Where the running install has got to, or null before one starts. */
  progress: AppUpdateProgress | null
  /**
   * The update is still coming, but the dialog is out of the way.
   *
   * A download runs for minutes, and the dialog used to refuse to close for
   * all of them — no Later, no close button, nothing to read. Putting it
   * aside does not cancel anything; the tray keeps the status and the dialog
   * comes back for the restart.
   */
  hidden: boolean
  installError: string | null
  check: () => Promise<void>
  install: () => Promise<void>
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
      pushToast({
        tone: 'success',
        title: 'EvoFlux is up to date',
        description: `You already have the latest version (${result.version}).`,
      })
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
  installing: false,
  progress: null,
  hidden: false,
  installError: null,

  handleResult: (result) => {
    const available = showResult(result)
    if (available) {
      set({ available, installError: null, progress: null, hidden: false })
    }
  },

  // Progress can only arrive during an install, but it is also the first
  // sign that one is under way after a restart-less retry — so it marks the
  // store as installing rather than assuming someone already did.
  handleProgress: (progress) =>
    set({
      progress,
      installing: true,
      // The install is the point of no return: whatever the user was doing,
      // the app is about to close, and it should not do that from behind a
      // dialog they put away ten minutes ago.
      hidden: progress.phase === 'installing' ? false : undefined,
    }),

  check: async () => {
    if (get().checking || get().installing) return
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

  install: async () => {
    if (!get().available || get().installing) return
    set({ installing: true, installError: null, progress: null })
    try {
      await installAppUpdate()
    } catch (error) {
      const message = errorMessage(error)
      set({ installing: false, installError: message, progress: null })
      useToastStore.getState().push(
        { tone: 'error', title: 'Update installation failed', description: message },
        8_000,
      )
    }
  },

  dismiss: () => {
    // Closing the dialog while an update downloads hides it; the download
    // keeps going and the dialog returns for the restart. Closing it before
    // one starts declines the update until the next check.
    if (get().installing) {
      if (get().progress?.phase !== 'installing') set({ hidden: true })
      return
    }
    set({ available: null, installError: null, progress: null, hidden: false })
  },
}))
