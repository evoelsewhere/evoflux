// Bridge to the engine processes managed by the Tauri shell — one per chat.
//
// The shell emits every engine stdout line as `engine://message`, stderr as
// `engine://stderr` and process exit as `engine://exit`, each tagged with the
// chat and the generation of the process that produced it. Restarting a
// chat's engine bumps its generation, so events from an older process are
// dropped here.

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { isMesh, meshCommand } from "./mesh";
import type { EngineMessage, ResponseMessage } from "./protocol";

export interface EngineInfo {
  binary: string;
  exists: boolean;
  extra_args: string[];
}

type Pending = {
  chat: string;
  resolve: (value: any) => void;
  reject: (error: Error) => void;
};

export interface EngineHandlers {
  onMessage: (chat: string, message: EngineMessage) => void;
  onStderr: (chat: string, line: string) => void;
  onExit: (chat: string, code: number | null) => void;
}

/** Every window hears every engine's events; ids carry the window's own prefix. */
const ID_PREFIX = `${Math.random().toString(36).slice(2, 8)}-`;

export class EngineClient {
  private generations = new Map<string, number>();
  private nextId = 1;
  private pending = new Map<string, Pending>();
  private unlisten: UnlistenFn[] = [];

  constructor(private handlers: EngineHandlers) {}

  async attach(): Promise<void> {
    this.unlisten.push(
      await listen<{ chat: string; generation: number; message: EngineMessage }>("engine://message", ({ payload }) => {
        if (!this.accept(payload.chat, payload.generation)) return;
        this.dispatch(payload.chat, payload.message);
      }),
      await listen<{ chat: string; generation: number; line: string }>("engine://stderr", ({ payload }) => {
        if (!this.accept(payload.chat, payload.generation)) return;
        this.handlers.onStderr(payload.chat, payload.line);
      }),
      await listen<{ chat: string; generation: number; code: number | null }>("engine://exit", ({ payload }) => {
        if (payload.generation !== this.generations.get(payload.chat)) return;
        this.failPending(payload.chat, "engine exited");
        this.handlers.onExit(payload.chat, payload.code);
      }),
    );
  }

  detach(): void {
    for (const stop of this.unlisten.splice(0)) stop();
  }

  info(): Promise<EngineInfo> {
    return invoke<EngineInfo>("engine_info");
  }

  /** The chats whose engine runs now. */
  running(): Promise<string[]> {
    return invoke<string[]>("engine_running");
  }

  /** Start (or restart) `chat`'s engine with `cwd` as the project directory. */
  async start(chat: string, cwd?: string): Promise<void> {
    this.failPending(chat, "engine restarted");
    // Events of the new process can arrive before `invoke` returns; `accept`
    // adopts the newer generation as soon as one shows up.
    const generation = await invoke<number>("engine_start", { chat, cwd: cwd ?? null });
    this.generations.set(chat, Math.max(this.generations.get(chat) ?? 0, generation));
  }

  async stop(chat: string): Promise<void> {
    this.failPending(chat, "engine stopped");
    this.generations.delete(chat);
    await invoke("engine_stop", { chat });
  }

  /** Send a command to `chat`'s engine and resolve with its `data` when the response arrives. */
  request<T = any>(chat: string, type: string, payload: Record<string, unknown> = {}): Promise<T> {
    const id = ID_PREFIX + String(this.nextId++);
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { chat, resolve, reject });
      invoke("engine_send", { chat, message: { ...payload, id, type } }).catch((error) => {
        this.pending.delete(id);
        reject(error instanceof Error ? error : new Error(String(error)));
      });
    });
  }

  /**
   * Send a session-mesh command (`subscribe`, `list`, `get`, `cancel`) to
   * `chat`'s engine and resolve with the body of its `res` envelope.
   */
  mesh<T = any>(chat: string, op: string, body: Record<string, unknown> = {}): Promise<T> {
    const id = ID_PREFIX + String(this.nextId++);
    const envelope = meshCommand(id, `client:${ID_PREFIX.slice(0, -1)}`, op, body);
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { chat, resolve, reject });
      invoke("engine_send", { chat, message: envelope }).catch((error) => {
        this.pending.delete(id);
        reject(error instanceof Error ? error : new Error(String(error)));
      });
    });
  }

  private accept(chat: string, generation: number): boolean {
    const current = this.generations.get(chat) ?? 0;
    if (generation < current) return false;
    this.generations.set(chat, generation);
    return true;
  }

  private dispatch(chat: string, message: EngineMessage): void {
    // A mesh answer correlates by `corr`; its error is `body.error`.
    if (isMesh(message) && message.kind === "res" && typeof message.corr === "string") {
      const pending = this.pending.get(message.corr);
      if (pending && pending.chat === chat) {
        this.pending.delete(message.corr);
        const error = message.body?.error;
        if (error) pending.reject(new Error(`${error.code}: ${error.message}`));
        else pending.resolve(message.body ?? null);
        return;
      }
    }
    if (message.type === "response" && typeof message.id === "string") {
      const pending = this.pending.get(message.id);
      if (pending && pending.chat === chat) {
        this.pending.delete(message.id);
        const response = message as ResponseMessage;
        if (response.success) pending.resolve(response.data ?? null);
        else pending.reject(new Error(response.error ?? `${response.command} failed`));
        return;
      }
    }
    this.handlers.onMessage(chat, message);
  }

  private failPending(chat: string, reason: string): void {
    for (const [id, pending] of this.pending) {
      if (pending.chat !== chat) continue;
      this.pending.delete(id);
      pending.reject(new Error(reason));
    }
  }
}
