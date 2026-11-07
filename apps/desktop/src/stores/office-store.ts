// The optional LibreOffice runtime that renders Office documents as exact
// pages: what the engine reports and the actions on it
// (docs/features/office/spec.md, docs/features/office-v3-parity/spec.md). The
// engine owns the install; this store asks it (RPC `office_*`, see
// crates/evo-engine/src/office.rs) and follows an install while it runs. It
// also holds the Files setting "Open generated documents automatically".

import * as React from "react";
import { create } from "zustand";
import { db } from "@/lib/db";
import { inTauri } from "@/lib/platform";
import { useEngineStore } from "./engine-store";

export type OfficePhase = "downloading" | "verifying" | "extracting" | "failed";

export interface OfficeJob {
  phase: OfficePhase;
  version: string;
  bytesDone: number;
  bytesTotal: number;
  startedAt: number;
  error: string | null;
}

export interface OfficeStatus {
  available: boolean;
  platform: string | null;
  version: string | null;
  downloadBytes: number | null;
  installBytes: number | null;
  installedVersion: string | null;
  job: OfficeJob | null;
}

export type OfficeAction = "office_install" | "office_cancel_install" | "office_dismiss_error" | "office_uninstall";

interface OfficeStore {
  status: OfficeStatus | null;
  /** The last status read's failure, e.g. an engine that predates the feature. */
  error: string | null;
  /** The action whose request is on its way (an install starting). */
  pending: OfficeAction | null;
  /** A failed install or cancel request (v3 `requestError`), until dismissed. */
  actionError: string | null;
  refresh(): Promise<void>;
  act(action: OfficeAction): Promise<void>;
  /** Forget `actionError`. */
  clearActionError(): void;
}

function message(error: unknown): string {
  return String(error).replace(/^Error:\s*/, "");
}

export const useOfficeStore = create<OfficeStore>((set) => ({
  status: null,
  error: null,
  pending: null,
  actionError: null,
  async refresh() {
    try {
      const status = await useEngineStore.getState().request<OfficeStatus>("office_status");
      set({ status, error: null });
    } catch (e) {
      set({ error: message(e) });
    }
  },
  async act(action) {
    set({ pending: action });
    try {
      const status = await useEngineStore.getState().request<OfficeStatus>(action);
      set({ status, error: null, actionError: null });
    } catch (e) {
      set({ actionError: message(e) });
    } finally {
      set({ pending: null });
    }
  },
  clearActionError: () => set({ actionError: null }),
}));

/** Whether a document can be rendered right now. */
export const officeReady = (status: OfficeStatus | null) => !!status?.installedVersion;

/** The status, refreshed when the engine is ready and every 700 ms while an install runs. */
export function useOffice() {
  const ready = useEngineStore((s) => (s.activeId ? s.runtimes[s.activeId]?.status === "ready" : false));
  const chat = useEngineStore((s) => s.activeId);
  const status = useOfficeStore((s) => s.status);
  const error = useOfficeStore((s) => s.error);
  const refresh = useOfficeStore((s) => s.refresh);
  const act = useOfficeStore((s) => s.act);
  React.useEffect(() => {
    if (ready) void refresh();
  }, [ready, chat, refresh]);
  const running = !!status?.job && status.job.phase !== "failed";
  React.useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void refresh(), 700);
    return () => clearInterval(timer);
  }, [running, refresh]);
  return { status, error, ready, act, refresh };
}

// ── Files: open generated documents ─────────────────────────────────────────

/** App setting (evo.db `settings`): open a document the agent creates in Files. Default on. */
export const AUTO_OPEN_GENERATED_KEY = "files.autoOpenGenerated";

/** Read fresh every time, so a change in another window counts at once. */
export async function autoOpenGeneratedEnabled(): Promise<boolean> {
  if (!inTauri) return true;
  try {
    return (await db.settings())[AUTO_OPEN_GENERATED_KEY] !== false;
  } catch {
    return true;
  }
}

export const setAutoOpenGenerated = (enabled: boolean) => db.setSetting(AUTO_OPEN_GENERATED_KEY, enabled);
