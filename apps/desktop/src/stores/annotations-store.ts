// The batch of document annotations waiting in a chat's composer, and the
// viewer's requests to send them now (docs/features/office-v3-parity/spec.md,
// FR-10; port of v3 useDocumentAnnotationsStore).
//
// The Files viewer adds annotations; the composer shows them as one chip,
// folds them into the next message it sends and clears them. `submitRequest`
// lets the viewer's "Send now" submit through the composer, so drafts,
// attachments and steering behave exactly as for typed messages. In memory
// only, keyed by chat id.

import { create } from "zustand";
import type { DocumentAnnotation } from "@/lib/document-annotations";

/** Annotations one message may carry. */
export const MAX_BATCH_ANNOTATIONS = 20;

interface AnnotationsState {
  pending: Record<string, DocumentAnnotation[]>;
  submitRequest: { chatId: string; nonce: number } | null;
  /** Add to the chat's batch; false when the batch is full. */
  add(chatId: string, annotation: DocumentAnnotation): boolean;
  remove(chatId: string, id: string): void;
  clear(chatId: string): void;
  /** Put a batch back after a failed send, unless a new one was started meanwhile. */
  restore(chatId: string, annotations: DocumentAnnotation[]): void;
  /** Ask the chat's composer to send now. */
  requestSubmit(chatId: string): void;
}

function without(pending: Record<string, DocumentAnnotation[]>, chatId: string) {
  const next = { ...pending };
  delete next[chatId];
  return next;
}

export const useAnnotationsStore = create<AnnotationsState>((set, get) => ({
  pending: {},
  submitRequest: null,
  add(chatId, annotation) {
    if ((get().pending[chatId]?.length ?? 0) >= MAX_BATCH_ANNOTATIONS) return false;
    set((state) => ({ pending: { ...state.pending, [chatId]: [...(state.pending[chatId] ?? []), annotation] } }));
    return true;
  },
  remove(chatId, id) {
    set((state) => {
      const next = (state.pending[chatId] ?? []).filter((item) => item.id !== id);
      return { pending: next.length > 0 ? { ...state.pending, [chatId]: next } : without(state.pending, chatId) };
    });
  },
  clear(chatId) {
    set((state) => (state.pending[chatId] ? { pending: without(state.pending, chatId) } : state));
  },
  restore(chatId, annotations) {
    set((state) =>
      annotations.length === 0 || state.pending[chatId]?.length ? state : { pending: { ...state.pending, [chatId]: annotations } },
    );
  },
  requestSubmit(chatId) {
    set((state) => ({ submitRequest: { chatId, nonce: (state.submitRequest?.nonce ?? 0) + 1 } }));
  },
}));

const EMPTY: DocumentAnnotation[] = [];

/** The chat's waiting annotations (a stable empty list when none). */
export function usePendingAnnotations(chatId: string | null | undefined): DocumentAnnotation[] {
  return useAnnotationsStore((state) => (chatId ? state.pending[chatId] : undefined) ?? EMPTY);
}
