import * as React from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { FolderOpenIcon, MessageSquareIcon, MoonIcon, PanelRightIcon, PlusIcon, RotateCwIcon } from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import { db, type DbChat } from "@/lib/db";
import { modKey } from "@/lib/platform";
import { useEngineStore } from "@/stores/engine-store";
import { useSessionStore } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";
import { panels } from "@/features/panels/panel-registry";

/** Search chats and run app commands (Ctrl/⌘ P). */
export function CommandPalette() {
  const commandOpen = useUiStore((s) => s.commandOpen);
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);
  const openPanel = useUiStore((s) => s.openPanel);
  const toggleRightPanel = useUiStore((s) => s.toggleRightPanel);
  const sessions = useSessionStore((s) => s.sessions);
  const { newChat, start, openWorkspace, selectSession } = useEngineStore.getState();
  const { resolved, setTheme } = useTheme();
  const [query, setQuery] = React.useState("");
  const [found, setFound] = React.useState<DbChat[]>([]);

  // Search inside conversations too (titles are matched by the list itself).
  React.useEffect(() => {
    const text = query.trim();
    if (text.length < 2) {
      setFound([]);
      return;
    }
    const timer = window.setTimeout(() => {
      db.searchChats(text).then(setFound, () => setFound([]));
    }, 150);
    return () => window.clearTimeout(timer);
  }, [query]);
  React.useEffect(() => {
    if (!commandOpen) setQuery("");
  }, [commandOpen]);
  const listed = new Set(sessions.filter((s) => !s.draft).map((s) => s.id));
  const inContent = found.filter((chat) => !listed.has(chat.id) || !chat.title.toLowerCase().includes(query.trim().toLowerCase()));

  const run = (action: () => void) => () => {
    setCommandOpen(false);
    action();
  };

  return (
    <CommandDialog open={commandOpen} onOpenChange={setCommandOpen} title="Search" description="Search chats and commands">
      <CommandInput placeholder="Search chats and commands…" value={query} onValueChange={setQuery} />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        <CommandGroup heading="Actions">
          <CommandItem onSelect={run(() => void newChat())}>
            <PlusIcon />
            New chat
            <CommandShortcut>{modKey} N</CommandShortcut>
          </CommandItem>
          <CommandItem
            onSelect={run(async () => {
              const folder = await open({ directory: true, multiple: false });
              if (typeof folder === "string") await openWorkspace(folder);
            })}
          >
            <FolderOpenIcon />
            Open folder…
            <CommandShortcut>{modKey} O</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={run(() => toggleRightPanel())}>
            <PanelRightIcon />
            Toggle side panel
            <CommandShortcut>{modKey} J</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={run(() => setTheme(resolved === "dark" ? "light" : "dark"))}>
            <MoonIcon />
            Toggle theme
          </CommandItem>
          <CommandItem onSelect={run(() => void start())}>
            <RotateCwIcon />
            Restart engine
          </CommandItem>
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Tools">
          {panels.map((panel) => (
            <CommandItem key={panel.id} onSelect={run(() => openPanel(panel.id))}>
              <panel.icon />
              {panel.title}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        {inContent.length > 0 && (
          <CommandGroup heading="In conversations" forceMount>
            {inContent.map((chat) => (
              <CommandItem key={`found-${chat.id}`} forceMount value={`found ${chat.id}`} onSelect={run(async () => {
                  // An archived chat is listed once the archive is loaded.
                  if (chat.archivedAt) await useSessionStore.getState().loadArchived();
                  await selectSession(chat.id);
                })}>
                <MessageSquareIcon />
                <span className="truncate">{chat.title}</span>
                {chat.archivedAt && <span className="ml-auto text-xs text-muted-foreground">Archived</span>}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        <CommandGroup heading="Recent chats">
          {sessions.filter((s) => !s.draft).map((session) => (
            <CommandItem key={session.id} value={`${session.title} ${session.id}`} onSelect={run(() => void selectSession(session.id))}>
              <MessageSquareIcon />
              <span className="truncate">{session.title}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
