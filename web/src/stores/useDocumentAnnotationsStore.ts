/**
 * useDocumentAnnotationsStore — the batch of document annotations waiting in
 * a session's composer, and requests from the viewer to send them now.
 *
 * The viewer adds annotations; the composer shows them as one chip, folds
 * them into the next message it submits and clears them. `submitRequest`
 * lets the viewer's "send" button submit through the composer, so drafts,
 * lanes and queueing behave exactly as for typed messages. In memory only.
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

import type { DocumentAnnotation } from '@/lib/document-annotations'

/** Annotations one message may carry. */
export const MAX_BATCH_ANNOTATIONS = 20

interface DocumentAnnotationsState {
  pending: Record<string, DocumentAnnotation[]>
  submitRequest: { sessionId: string; nonce: number } | null
  add: (sessionId: string, annotation: DocumentAnnotation) => boolean
  remove: (sessionId: string, id: string) => void
  clear: (sessionId: string) => void
  restore: (sessionId: string, annotations: DocumentAnnotation[]) => void
  requestSubmit: (sessionId: string) => void
}

export const useDocumentAnnotationsStore = create<DocumentAnnotationsState>()(
  immer((set, get) => ({
    pending: {},
    submitRequest: null,
    add: (sessionId, annotation) => {
      if ((get().pending[sessionId]?.length ?? 0) >= MAX_BATCH_ANNOTATIONS) return false
      set((state) => {
        state.pending[sessionId] = [...(state.pending[sessionId] ?? []), annotation]
      })
      return true
    },
    remove: (sessionId, id) => set((state) => {
      const next = (state.pending[sessionId] ?? []).filter((item) => item.id !== id)
      if (next.length > 0) state.pending[sessionId] = next
      else delete state.pending[sessionId]
    }),
    clear: (sessionId) => set((state) => {
      delete state.pending[sessionId]
    }),
    restore: (sessionId, annotations) => set((state) => {
      if (annotations.length === 0 || state.pending[sessionId]?.length) return
      state.pending[sessionId] = annotations
    }),
    requestSubmit: (sessionId) => set((state) => {
      state.submitRequest = { sessionId, nonce: (state.submitRequest?.nonce ?? 0) + 1 }
    }),
  })),
)

const EMPTY: DocumentAnnotation[] = []

export function usePendingAnnotations(sessionId: string | null | undefined): DocumentAnnotation[] {
  return useDocumentAnnotationsStore((state) => (sessionId ? state.pending[sessionId] : undefined) ?? EMPTY)
}
