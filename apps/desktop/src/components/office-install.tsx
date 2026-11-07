import { CircleAlertIcon, DownloadIcon, Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { formatBytes } from "@/lib/format";
import { useOffice, type OfficeJob } from "@/stores/office-store";

// Install, follow, cancel and remove the Office renderer (the LibreOffice
// runtime). Used by Settings → Office and by the document viewer when a file
// needs it. The engine does the work: crates/evo-engine/src/office.rs.

const PHASE: Record<OfficeJob["phase"], string> = {
  downloading: "Downloading",
  verifying: "Verifying",
  extracting: "Installing",
  failed: "Failed",
};

/** One line of what the install is doing, with a progress bar while it downloads. */
export function OfficeProgress({ job }: { job: OfficeJob }) {
  const percent = job.bytesTotal ? Math.min(100, (job.bytesDone / job.bytesTotal) * 100) : 0;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3 text-[13px] text-muted-foreground">
        <span className="flex items-center gap-2">
          <Spinner className="size-3.5" />
          {PHASE[job.phase]}
          {job.phase === "downloading" && ` ${formatBytes(job.bytesDone)} of ${formatBytes(job.bytesTotal)}`}
        </span>
        {job.phase === "downloading" && <span className="tabular-nums">{Math.floor(percent)}%</span>}
      </div>
      <Progress value={job.phase === "downloading" ? percent : null} aria-label="Office renderer install" />
    </div>
  );
}

/** What can be done with the renderer right now, as buttons. */
export function OfficeActions({ size = "sm" }: { size?: "sm" | "default" }) {
  const { status, ready, act } = useOffice();
  if (!status) return null;
  const job = status.job;
  if (job && job.phase !== "failed") {
    const cancellable = job.phase === "downloading" || job.phase === "verifying";
    return (
      <Button size={size} variant="outline" disabled={!cancellable} onClick={() => void act("office_cancel_install")}>
        Cancel
      </Button>
    );
  }
  if (job?.phase === "failed") {
    return (
      <div className="flex gap-2">
        <Button size={size} variant="outline" onClick={() => void act("office_dismiss_error")}>
          Dismiss
        </Button>
        <Button size={size} disabled={!ready} onClick={() => void act("office_install")} className="gap-1.5">
          <DownloadIcon className="size-3.5" /> Retry
        </Button>
      </div>
    );
  }
  if (status.installedVersion) {
    return (
      <Button size={size} variant="outline" className="gap-1.5" onClick={() => void act("office_uninstall")}>
        <Trash2Icon className="size-3.5" /> Remove
      </Button>
    );
  }
  if (!status.available) return null;
  return (
    <Button size={size} disabled={!ready} onClick={() => void act("office_install")} className="gap-1.5">
      <DownloadIcon className="size-3.5" /> Install{status.downloadBytes ? ` (${formatBytes(status.downloadBytes)})` : ""}
    </Button>
  );
}

/** A failed install's message. */
export function OfficeError({ job }: { job: OfficeJob | null }) {
  if (job?.phase !== "failed" || !job.error) return null;
  return (
    <p className="flex items-start gap-2 text-[13px] text-destructive">
      <CircleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
      <span className="min-w-0 break-words">{job.error}</span>
    </p>
  );
}
