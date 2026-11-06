// What you can do with a path: attach it to the next message, open it in an
// app, show it in the file manager, copy it. Shared by the explorer, the open
// file's header and file paths elsewhere.

import { openPath, revealItemInDir } from "@tauri-apps/plugin-opener";
import { composerDraft } from "@/features/chat/chat-composer";
import {
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";
import { isMac, isWindows } from "@/lib/platform";
import { openInApp, useOpenApps } from "@/lib/open-apps";
import { fileName, relativePath } from "./fs";

const MANAGER = isMac ? "Finder" : isWindows ? "Explorer" : "file manager";

function copy(text: string) {
  void navigator.clipboard.writeText(text).catch(() => undefined);
}

export function PathMenuItems({
  path,
  root,
  dir = false,
  onOpen,
}: {
  path: string;
  /** For the relative path. */
  root?: string;
  dir?: boolean;
  /** Open in the Files tool (files only). */
  onOpen?(): void;
}) {
  const apps = useOpenApps().filter((app) => (dir ? true : app.kind === "editor"));
  return (
    <>
      <DropdownMenuGroup>
        {onOpen && !dir && <DropdownMenuItem onClick={onOpen}>Open</DropdownMenuItem>}
        <DropdownMenuItem onClick={() => composerDraft.attach(path)}>Attach as context</DropdownMenuItem>
        {apps.length > 0 && (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>Open in</DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="w-52">
              {apps.map((app) => (
                <DropdownMenuItem key={app.id} onClick={() => void openInApp(app.id, path).catch(() => undefined)}>
                  {app.icon ? <img src={app.icon} alt="" className="size-4" /> : null}
                  {app.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}
        {!dir && (
          <DropdownMenuItem onClick={() => void openPath(path).catch(() => undefined)}>Open with default app</DropdownMenuItem>
        )}
        <DropdownMenuItem onClick={() => void revealItemInDir(path).catch(() => undefined)}>Show in {MANAGER}</DropdownMenuItem>
      </DropdownMenuGroup>
      <DropdownMenuSeparator />
      <DropdownMenuGroup>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>Copy</DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="w-44">
            <DropdownMenuItem onClick={() => copy(path)}>Absolute path</DropdownMenuItem>
            {root && (
              <DropdownMenuItem onClick={() => copy(relativePath(root, path))}>Relative path</DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={() => copy(fileName(path))}>{dir ? "Folder name" : "File name"}</DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
      </DropdownMenuGroup>
    </>
  );
}
