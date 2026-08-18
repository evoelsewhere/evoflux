import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

import type { ChangeSetResponse } from '@/api/types'

interface ChangeSetStore {
  active: ChangeSetResponse | null
  busy: boolean
  setActive: (changeSet: ChangeSetResponse | null) => void
  setBusy: (busy: boolean) => void
}

export const useChangeSetStore = create<ChangeSetStore>()(
  immer((set) => ({
    active: null,
    busy: false,
    setActive: (changeSet) => {
      set((state) => {
        state.active = changeSet
      })
    },
    setBusy: (busy) => {
      set((state) => {
        state.busy = busy
      })
    },
  })),
)
