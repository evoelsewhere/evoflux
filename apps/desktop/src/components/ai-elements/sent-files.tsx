import { ExternalLinkIcon, FileIcon, FolderOpenIcon, PanelRightIcon } from "lucide-react";
import { openPath, revealItemInDir } from "@tauri-apps/plugin-opener";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatBytes } from "@/lib/format";
import { openFile } from "@/stores/files-store";

// Files the agent sent (`send_file`): a card each, to open with the default
// app, show in its folder, or view in the Files tool.

export interface SentFile {
  path: string;
  name: string;
  size: number;
}

function Action({ label, onClick, children }: { label: string; onClick(): void; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger render={<Button size="icon-sm" variant="ghost" aria-label={label} onClick={onClick} className="size-7 text-muted-foreground" />}>
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function SentFiles({ files, caption }: { files: SentFile[]; caption?: string }) {
  return (
    <div className="flex flex-col gap-1.5 pt-1 pb-2 pl-7">
      {caption && <p className="text-[13px] text-muted-foreground">{caption}</p>}
      <div className="grid gap-1.5 @lg:grid-cols-2">
        {files.map((file) => {
          const folder = file.path.slice(0, file.path.length - file.name.length).replace(/[\\/]$/, "");
          return (
            <div key={file.path} className="flex min-w-0 items-center gap-2.5 rounded-xl px-3 py-2 ring-1 ring-border">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand/12 text-brand">
                <FileIcon className="size-4" />
              </span>
              <button
                type="button"
                onClick={() => void openPath(file.path).catch(() => openFile(file.path))}
                className="flex min-w-0 flex-1 flex-col text-left"
                title={file.path}
              >
                <span className="truncate text-[13px] font-medium">{file.name}</span>
                <span className="truncate text-[11px] text-muted-foreground">
                  {formatBytes(file.size)} · {folder}
                </span>
              </button>
              <Action label="Open" onClick={() => void openPath(file.path).catch(() => openFile(file.path))}>
                <ExternalLinkIcon className="size-3.5" />
              </Action>
              <Action label="View in Files" onClick={() => openFile(file.path)}>
                <PanelRightIcon className="size-3.5" />
              </Action>
              <Action label="Show in folder" onClick={() => void revealItemInDir(file.path).catch(() => undefined)}>
                <FolderOpenIcon className="size-3.5" />
              </Action>
            </div>
          );
        })}
      </div>
    </div>
  );
}
