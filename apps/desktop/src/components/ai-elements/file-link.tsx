import * as React from "react";
import { resolvePath } from "@/features/files/fs";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { openFile } from "@/stores/files-store";

/**
 * A file path in the transcript: click opens it in the Files tool (at `line`),
 * without toggling the row it sits in.
 */
export function FileLink({
  path,
  line,
  className,
  label,
}: {
  path: string;
  line?: number;
  className?: string;
  /** Shown instead of the path (a file name). */
  label?: string;
}) {
  const open = (event: React.SyntheticEvent) => {
    event.preventDefault();
    event.stopPropagation();
    const root = useEngineStore.getState().cwd ?? "";
    void openFile(root ? resolvePath(root, path) : path, line);
  };
  return (
    <span
      role="link"
      tabIndex={0}
      title={line ? `Open ${path} at line ${line}` : `Open ${path}`}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === "Enter") open(event);
      }}
      className={cn("cursor-pointer underline-offset-2 hover:text-link hover:underline", className)}
    >
      {label ?? path}
    </span>
  );
}
