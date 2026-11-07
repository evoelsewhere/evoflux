// The optional LibreOffice runtime that renders Office documents: what the
// engine reports and the actions on it (docs/features/office/sdd.md). The
// engine owns the install; this store asks it (RPC `office_*`, see
// crates/evo-engine/src/office.rs) and follows an install while it runs.

import * as React from "react";
import { create } from "zustand";
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
  /** The last request's failure, e.g. an engine that predates the feature. */
  error: string | null;
  refresh(): Promise<void>;
  act(action: OfficeAction): Promise<void>;
}

function message(error: unknown): string {
  return String(error).replace(/^Error:\s*/, "");
}

export const useOfficeStore = create<OfficeStore>((set) => {
  const ask = async (type: string) => {
    try {
      const status = await useEngineStore.getState().request<OfficeStatus>(type);
      set({ status, error: null });
    } catch (e) {
      set({ error: message(e) });
    }
  };
  return {
    status: null,
    error: null,
    refresh: () => ask("office_status"),
    act: (action) => ask(action),
  };
});

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
