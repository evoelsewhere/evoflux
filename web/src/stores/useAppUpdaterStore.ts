import { create } from 'zustand'

import {
  checkForAppUpdates,
  installAppUpdate,
  type AppUpdateCheckResult,
} from '@/lib/app-updater'
import { useToastStore } from '@/stores/useToastStore'

type AvailableUpdate = Extract<AppUpdateCheckResult, { status: 'available' }>

interface AppUpdaterStore {
  available: AvailableUpdate | null
  checking: boolean
  installing: boolean
  installError: string | null
  check: () => Promise<void>
  install: () => Promise<void>
  dismiss: () => void
  handleResult: (result: AppUpdateCheckResult) => void
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
  installError: null,

  handleResult: (result) => {
    const available = showResult(result)
    if (available) {
      set({ available, installError: null })
    }
  },

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
    set({ installing: true, installError: null })
    try {
      await installAppUpdate()
    } catch (error) {
      const message = errorMessage(error)
      set({ installing: false, installError: message })
      useToastStore.getState().push(
        { tone: 'error', title: 'Update installation failed', description: message },
        8_000,
      )
    }
  },

  dismiss: () => {
    if (get().installing) return
    set({ available: null, installError: null })
  },
}))
