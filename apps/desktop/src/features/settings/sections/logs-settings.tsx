import * as React from "react";
import { DatabaseIcon, DownloadIcon, FolderOpenIcon, PauseIcon, PlayIcon, RefreshCwIcon, ScrollTextIcon, Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { db, type DbInfo, type LogEntry, type LogLevel, type LogQuery } from "@/lib/db";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { useSessionStore } from "@/stores/session-store";
import { Segmented, SettingsGroup, SettingsHeader, SettingsRow } from "../settings-controls";

// The data kept on this machine and the run log: where the database lives,
// how big it is, and a viewer over the log the shell, the engines and the UI
// write — filter, follow live, export, clear.

const PAGE = 300;

const levelTone: Record<LogLevel, string> = {
  debug: "text-muted-foreground",
  info: "text-foreground",
  warn: "text-status-warn",
  error: "text-destructive",
};

function time(at: number) {
  const date = new Date(at);
  const pad = (n: number, width = 2) => String(n).padStart(width, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

function LogRow({ entry, chatTitle }: { entry: LogEntry; chatTitle?: string }) {
  const [open, setOpen] = React.useState(false);
  const hasData = entry.data !== null && entry.data !== undefined;
  return (
    <div className="border-b border-border/50 px-3 py-1 last:border-b-0 hover:bg-muted/40">
      <button
        type="button"
        disabled={!hasData}
        onClick={() => setOpen((v) => !v)}
        className="grid w-full grid-cols-[8.5rem_3rem_4.5rem_minmax(0,1fr)] items-baseline gap-2 text-left disabled:cursor-text"
      >
        <span className="text-muted-foreground tabular-nums">{time(entry.atMs)}</span>
        <span className={cn("font-semibold uppercase", levelTone[entry.level])}>{entry.level}</span>
        <span className="truncate text-muted-foreground">{entry.source}</span>
        <span className="min-w-0 break-words whitespace-pre-wrap" data-selectable>
          {entry.message}
          {chatTitle && <span className="ml-2 text-muted-foreground">· {chatTitle}</span>}
          {hasData && !open && <span className="ml-2 text-muted-foreground">{"{…}"}</span>}
        </span>
      </button>
      {open && hasData && (
        <pre className="mt-1 mb-1 ml-[16.5rem] overflow-x-auto rounded-md bg-muted/60 p-2 text-[11px]" data-selectable>
          {JSON.stringify(entry.data, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function LogsSettings() {
  const sessions = useSessionStore((s) => s.sessions);
  const activeId = useEngineStore((s) => s.activeId);
  const running = useEngineStore((s) => Object.keys(s.runtimes).length);
  const [info, setInfo] = React.useState<DbInfo>();
  const [entries, setEntries] = React.useState<LogEntry[]>([]);
  const [level, setLevel] = React.useState<LogLevel>("info");
  const [source, setSource] = React.useState("all");
  const [thisChat, setThisChat] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [live, setLive] = React.useState(true);
  const [more, setMore] = React.useState(false);
  const [notice, setNotice] = React.useState<string>();

  const query = React.useMemo<LogQuery>(
    () => ({
      minLevel: level,
      source: source === "all" ? undefined : source,
      chatId: thisChat && activeId ? activeId : undefined,
      search: search.trim() || undefined,
    }),
    [level, source, thisChat, activeId, search],
  );

  const refresh = React.useCallback(async () => {
    const [rows, next] = await Promise.all([db.queryLogs({ ...query, limit: PAGE }), db.info()]);
    setEntries(rows);
    setMore(rows.length === PAGE);
    setInfo(next);
  }, [query]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  React.useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [live, refresh]);

  async function older() {
    const last = entries.at(-1);
    if (!last) return;
    setLive(false);
    const rows = await db.queryLogs({ ...query, beforeId: last.id, limit: PAGE });
    setEntries((current) => [...current, ...rows]);
    setMore(rows.length === PAGE);
  }

  const titles = React.useMemo(() => new Map(sessions.map((s) => [s.id, s.title])), [sessions]);
  const sources = ["all", ...(info?.logs.sources ?? [])];

  return (
    <div className="flex flex-col gap-8">
      <SettingsHeader
        icon={ScrollTextIcon}
        title="Data & logs"
        description="Chats, settings and the run log are kept in a database on this computer, and each chat's conversation in a file of its own. The log records what the app and its engines did, for debugging."
      />

      <SettingsGroup title="Stored on this computer">
        <SettingsRow
          label="Database"
          description={<span className="font-mono text-xs break-all">{info?.path ?? "…"}</span>}
          control={
            <Button variant="outline" size="sm" onClick={() => void db.reveal()}>
              <FolderOpenIcon />
              Show in folder
            </Button>
          }
        />
        <SettingsRow
          label="Size"
          description={`Schema version ${info?.schemaVersion ?? "…"} · ${sessions.filter((s) => !s.draft).length} chats · ${running} engine${running === 1 ? "" : "s"} running`}
          control={
            <span className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
              <DatabaseIcon className="size-3.5" />
              {info ? formatBytes(info.sizeBytes) : "…"}
            </span>
          }
        />
        <SettingsRow
          label="Transcripts"
          description={
            <>
              {`${info?.transcriptsCount.toLocaleString() ?? "…"} files, one per chat, in `}
              <span className="font-mono text-xs break-all">{info?.transcriptsDir ?? "…"}</span>
            </>
          }
          control={
            <span className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
              <DatabaseIcon className="size-3.5" />
              {info ? formatBytes(info.transcriptsBytes) : "…"}
            </span>
          }
        />
        <SettingsRow
          label="Run log"
          description={`${info?.logs.count.toLocaleString() ?? "…"} entries, kept for 14 days (at most 50,000).`}
          control={
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  void db.exportLogs(query).then((path) => setNotice(`Exported to ${path}`), (error) => setNotice(String(error)))
                }
              >
                <DownloadIcon />
                Export
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void db.clearLogs().then(() => refresh())}
              >
                <Trash2Icon />
                Clear
              </Button>
            </div>
          }
        />
        {notice && <p className="pb-3 font-mono text-xs break-all text-muted-foreground">{notice}</p>}
      </SettingsGroup>

      <section className="flex min-h-0 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-sm font-semibold">Log</h2>
          <Button variant="ghost" size="sm" onClick={() => setLive((v) => !v)} aria-pressed={live}>
            {live ? <PauseIcon /> : <PlayIcon />}
            {live ? "Live" : "Paused"}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void refresh()}>
            <RefreshCwIcon />
            Refresh
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented<LogLevel>
            value={level}
            onValueChange={setLevel}
            options={[
              { value: "debug", label: "All" },
              { value: "info", label: "Info" },
              { value: "warn", label: "Warnings" },
              { value: "error", label: "Errors" },
            ]}
          />
          <Segmented value={source} onValueChange={setSource} options={sources.map((s) => ({ value: s, label: s === "all" ? "Every source" : s }))} />
          <Button variant={thisChat ? "secondary" : "ghost"} size="sm" onClick={() => setThisChat((v) => !v)} aria-pressed={thisChat}>
            This chat
          </Button>
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search the log…"
            className="h-8 w-48"
          />
        </div>
        <div className="max-h-[28rem] overflow-y-auto rounded-xl bg-card font-mono text-xs shadow-hairline">
          {entries.length === 0 ? (
            <p className="px-3 py-6 text-center font-sans text-sm text-muted-foreground">Nothing logged for these filters.</p>
          ) : (
            entries.map((entry) => (
              <LogRow key={entry.id} entry={entry} chatTitle={entry.chatId ? titles.get(entry.chatId) : undefined} />
            ))
          )}
          {more && (
            <div className="p-2 text-center">
              <Button variant="ghost" size="sm" onClick={() => void older()}>
                Load older
              </Button>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
