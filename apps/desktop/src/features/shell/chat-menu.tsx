import * as React from "react";
import { AppWindowIcon, CheckIcon, FolderIcon, LaptopIcon } from "lucide-react";
import {
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";
import { notify } from "@/features/notifications/notify";
import { openInApp, useOpenApps, type OpenApp } from "@/lib/open-apps";
import { chatWindowId } from "@/lib/windows";
import { useEngineStore } from "@/stores/engine-store";
import { useSessionStore, type SessionSummary } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";
import { AppIcon } from "./open-in-menu";

// A chat's actions, as the sidebar's right-click menu and "…" button show
// them. Each action has a one-key shortcut while the menu is open: letters on
// the menu, digits in "Open in".

interface Action {
  key: string;
  label: string;
  run(): void;
  disabled?: boolean;
  destructive?: boolean;
}

interface ChatMenuProps {
  chat: SessionSummary;
  active: boolean;
  onRename(): void;
  onDelete(): void;
  /** Close the menu (after a shortcut key ran an action). */
  onClose(): void;
}

function useChatActions({ chat, active, onRename, onDelete }: ChatMenuProps) {
  const busy = useEngineStore((s) => Boolean(s.runtimes[chat.id]?.transcript.busy || s.busyElsewhere[chat.id]));
  const workspace = useSessionStore((s) => s.workspaces.find((w) => w.id === chat.workspaceId));
  const apps = useOpenApps();
  const setLastApp = useUiStore((s) => s.setOpenInApp);
  const { openInNewWindow, forkChat, closeChat } = useEngineStore.getState();
  const { setPinned, setArchived, markUnread } = useSessionStore.getState();
  const archived = chat.archivedAt != null;
  const folder = workspace?.path;

  const launch = (app: OpenApp) => {
    if (!folder) return;
    openInApp(app.id, folder)
      .then(() => setLastApp(app.id))
      .catch((error: unknown) =>
        notify({ title: `Could not open in ${app.name}`, body: String(error), level: "error", source: "shell" }),
      );
  };

  const main: Action[] = archived
    ? [{ key: "a", label: "Restore", run: () => void setArchived(chat.id, false) }]
    : [
        { key: "p", label: chat.pinned ? "Unpin" : "Pin", run: () => void setPinned(chat.id, !chat.pinned) },
        { key: "u", label: "Mark as unread", run: () => markUnread(chat.id, true), disabled: chat.unread || active },
        { key: "r", label: "Rename", run: onRename },
        { key: "f", label: "Fork", run: () => void forkChat(chat.id), disabled: busy },
        { key: "a", label: "Archive", run: () => void closeChat(chat.id, "archive") },
      ];
  main.push({ key: "d", label: "Delete", run: onDelete, destructive: true });

  const newWindow: Action | null =
    archived || chatWindowId ? null : { key: "1", label: "New window", run: () => void openInNewWindow(chat.id) };
  const openIn = folder
    ? apps
        .filter((app) => app.kind !== "terminal")
        .concat(apps.filter((app) => app.kind === "terminal"))
        .map((app, index) => ({ app, key: String(index + 2), run: () => launch(app) }))
        // Digits run out at 9.
        .filter((entry) => entry.key.length === 1)
    : [];

  return { main, newWindow, openIn, busy, archived };
}

/** Run the action whose key was pressed (no modifiers) and close the menu. */
function shortcutHandler(actions: { key: string; run(): void; disabled?: boolean }[], onClose: () => void) {
  return (event: React.KeyboardEvent) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    // Keys from a submenu bubble here through React's portal; they are its own.
    if (!event.currentTarget.contains(event.target as Node)) return;
    const action = actions.find((a) => a.key === event.key.toLowerCase());
    if (!action) return;
    event.preventDefault();
    event.stopPropagation();
    if (action.disabled) return;
    onClose();
    action.run();
  };
}

/** The menu's key handler, for the popup that holds `ChatMenuItems`. */
export function useChatMenuKeys(props: ChatMenuProps) {
  const { main } = useChatActions(props);
  return shortcutHandler(main, props.onClose);
}

function Item({ action }: { action: Action }) {
  return (
    <DropdownMenuItem variant={action.destructive ? "destructive" : "default"} disabled={action.disabled} onClick={action.run}>
      {action.label}
      <DropdownMenuShortcut>{action.key.toUpperCase()}</DropdownMenuShortcut>
    </DropdownMenuItem>
  );
}

/** The menu body: Open in ›, Pin, Mark as unread, Rename, Fork, Move to ›, Archive, Delete. */
export function ChatMenuItems(props: ChatMenuProps) {
  const { chat, onClose } = props;
  const { main, newWindow, openIn, busy, archived } = useChatActions(props);
  const workspaces = useSessionStore((s) => s.workspaces);
  const moveChat = useEngineStore((s) => s.moveChat);
  const parent = useSessionStore((s) => (chat.parentChatId ? s.sessions.find((x) => x.id === chat.parentChatId) : undefined));
  const selectSession = useEngineStore((s) => s.selectSession);
  const setParent = useSessionStore((s) => s.setParent);
  const byKey = (key: string) => main.find((a) => a.key === key);
  const subActions = [...(newWindow ? [newWindow] : []), ...openIn];
  const places = [{ id: null as string | null, name: "This computer" }, ...workspaces.map((w) => ({ id: w.id as string | null, name: w.name }))];

  return (
    <>
      {subActions.length > 0 && (
        <>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>Open in</DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="w-56" onKeyDown={shortcutHandler(subActions, onClose)}>
              {newWindow && (
                <DropdownMenuItem onClick={newWindow.run}>
                  <AppWindowIcon className="text-muted-foreground" />
                  New window
                  <DropdownMenuShortcut>1</DropdownMenuShortcut>
                </DropdownMenuItem>
              )}
              {openIn.length > 0 && (
                <>
                  {newWindow && <DropdownMenuSeparator />}
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>Open in</DropdownMenuLabel>
                    {openIn.map(({ app, key, run }) => (
                      <DropdownMenuItem key={app.id} onClick={run}>
                        <AppIcon app={app} />
                        <span className="truncate">{app.name}</span>
                        <DropdownMenuShortcut>{key}</DropdownMenuShortcut>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuGroup>
                </>
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSeparator />
        </>
      )}
      {parent && (
        <>
          <DropdownMenuItem onClick={() => void selectSession(parent.id)}>
            <span className="truncate">Open parent · {parent.title}</span>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => void setParent(chat.id, null)}>Detach from parent</DropdownMenuItem>
          <DropdownMenuSeparator />
        </>
      )}
      {archived ? (
        <Item action={byKey("a")!} />
      ) : (
        <>
          {(["p", "u", "r", "f"] as const).map((key) => (
            <Item key={key} action={byKey(key)!} />
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuSub>
            <DropdownMenuSubTrigger disabled={busy}>Move to</DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="w-56">
              <DropdownMenuGroup>
                <DropdownMenuLabel>Workspace</DropdownMenuLabel>
                {places.map((place) => {
                  const current = (chat.workspaceId ?? null) === place.id;
                  const Icon = place.id ? FolderIcon : LaptopIcon;
                  return (
                    <DropdownMenuItem key={place.id ?? "local"} disabled={current} onClick={() => void moveChat(chat.id, place.id)}>
                      <Icon className="text-muted-foreground" />
                      <span className="truncate">{place.name}</span>
                      {current && <CheckIcon className="ml-auto text-muted-foreground" />}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuGroup>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSeparator />
          <Item action={byKey("a")!} />
        </>
      )}
      <Item action={byKey("d")!} />
    </>
  );
}
