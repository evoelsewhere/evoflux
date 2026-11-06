import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { CheckIcon, ChevronDownIcon, CodeIcon, CopyIcon, FolderIcon, SquareTerminalIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { notify } from "@/features/notifications/notify";
import { openInApp, useOpenApps, type OpenApp } from "@/lib/open-apps";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

const GLYPH = { fileManager: FolderIcon, editor: CodeIcon, terminal: SquareTerminalIcon } as const;

/** The app's own icon, or a glyph for its kind when the OS gave none. */
export function AppIcon({ app, className }: { app: OpenApp; className?: string }) {
  if (app.icon) {
    return <img src={app.icon} alt="" draggable={false} className={cn("size-4 shrink-0 object-contain", className)} />;
  }
  const Glyph = GLYPH[app.kind];
  return <Glyph className={cn("size-4 shrink-0 text-muted-foreground", className)} />;
}

/**
 * Open the workspace folder in another app: one click reopens it in the app
 * used last (the file manager until then); the chevron lists every file
 * manager, editor and terminal the shell found.
 */
export function OpenInMenu({ cwd }: { cwd: string }) {
  const apps = useOpenApps();
  const lastId = useUiStore((s) => s.openInApp);
  const setLast = useUiStore((s) => s.setOpenInApp);
  const primary = apps.find((a) => a.id === lastId) ?? apps.find((a) => a.kind === "fileManager") ?? apps[0];
  const places = apps.filter((a) => a.kind !== "terminal");
  const terminals = apps.filter((a) => a.kind === "terminal");

  function launch(app: OpenApp) {
    openInApp(app.id, cwd)
      .then(() => setLast(app.id))
      .catch((error: unknown) =>
        notify({ title: `Could not open in ${app.name}`, body: String(error), level: "error", source: "shell" }),
      );
  }

  const item = (app: OpenApp) => (
    <DropdownMenuItem key={app.id} onClick={() => launch(app)}>
      <AppIcon app={app} />
      <span className="truncate">{app.name}</span>
      {app.id === primary?.id && <CheckIcon className="ml-auto text-muted-foreground" />}
    </DropdownMenuItem>
  );

  return (
    <div className="flex items-center">
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="ghost"
              size="sm"
              className="h-7 rounded-r-none pr-1 pl-2 text-muted-foreground"
              aria-label={primary ? `Open in ${primary.name}` : "Show in file manager"}
              onClick={() => (primary ? launch(primary) : void revealItemInDir(cwd))}
            />
          }
        >
          {primary ? <AppIcon app={primary} /> : <FolderIcon />}
        </TooltipTrigger>
        <TooltipContent>{primary ? `Open in ${primary.name}` : "Show in file manager"}</TooltipContent>
      </Tooltip>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              className="h-7 w-5 rounded-l-none text-muted-foreground data-popup-open:bg-accent"
              aria-label="Open in…"
            />
          }
        >
          <ChevronDownIcon className="size-3.5" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Open in</DropdownMenuLabel>
            {places.length > 0 ? (
              places.map(item)
            ) : (
              <DropdownMenuItem onClick={() => void revealItemInDir(cwd)}>
                <FolderIcon />
                File manager
              </DropdownMenuItem>
            )}
          </DropdownMenuGroup>
          {terminals.length > 0 && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>{terminals.map(item)}</DropdownMenuGroup>
            </>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => void navigator.clipboard?.writeText(cwd).catch(() => undefined)}>
            <CopyIcon />
            Copy path
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
