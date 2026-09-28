/**
 * Tiny client-state store for ephemeral toasts. Emits a short banner
 * (success / error / info) that auto-dismisses after `durationMs`. Lives
 * outside TanStack Query because toasts are UI-only, not server state.
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

export type ToastTone = 'success' | 'error' | 'info'

export interface Toast {
  id: string
  tone: ToastTone
  title: string
  description?: string
}

interface ToastStore {
  toasts: Toast[]
  push: (t: Omit<Toast, 'id'>, durationMs?: number) => void
  dismiss: (id: string) => void
}

const dismissTimers = new Map<string, ReturnType<typeof setTimeout>>()

export const useToastStore = create<ToastStore>()(
  immer((set, get) => ({
    toasts: [],
    push: (t, durationMs = 4500) => {
      // The same failure reported again (a retried mutation, a toggle clicked
      // repeatedly) extends the visible toast instead of stacking copies.
      const existing = get().toasts.find(
        (toast) =>
          toast.tone === t.tone &&
          toast.title === t.title &&
          toast.description === t.description,
      )
      const id = existing?.id ?? `t-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
      if (!existing) {
        set((state) => {
          state.toasts.push({ id, ...t })
        })
      }
      clearTimeout(dismissTimers.get(id))
      dismissTimers.set(id, setTimeout(() => get().dismiss(id), durationMs))
    },
    dismiss: (id) => {
      clearTimeout(dismissTimers.get(id))
      dismissTimers.delete(id)
      set((state) => {
        state.toasts = state.toasts.filter((t) => t.id !== id)
      })
    },
  }))
)
