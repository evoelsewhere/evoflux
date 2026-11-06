// "Open in": apps on this machine that can open a workspace folder, as the
// shell detects them (src-tauri/src/apps.rs), each with its own icon.

import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";
import { inTauri } from "@/lib/platform";

export type OpenAppKind = "fileManager" | "editor" | "terminal";

export interface OpenApp {
  id: string;
  name: string;
  kind: OpenAppKind;
  /** Data URL of the app's icon; absent when the OS gave none. */
  icon?: string | null;
}

let pending: Promise<OpenApp[]> | null = null;

/** The detected apps; the shell builds the list once per run. */
export function loadOpenApps(): Promise<OpenApp[]> {
  if (!inTauri) return Promise.resolve([]);
  pending ??= invoke<OpenApp[]>("open_apps").catch(() => {
    pending = null;
    return [];
  });
  return pending;
}

export function useOpenApps(): OpenApp[] {
  const [apps, setApps] = useState<OpenApp[]>([]);
  useEffect(() => {
    let live = true;
    void loadOpenApps().then((list) => live && setApps(list));
    return () => {
      live = false;
    };
  }, []);
  return apps;
}

export function openInApp(id: string, path: string): Promise<void> {
  return invoke("open_in_app", { id, path });
}
