import * as React from "react";
import { CircleAlertIcon, DownloadIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { formatBytes } from "@/lib/format";
import { useOffice, useOfficeStore, type OfficeJob } from "@/stores/office-store";

// Install, follow and cancel the Office renderer (the LibreOffice runtime).
// Shown by the document viewer when an Office file needs it: there is no
// settings page for it. The engine does the work: crates/evo-engine/src/office.rs.
// `OfficeRuntimeBanner` is the v3 banner over a native (approximate) preview.

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
  if (status.installedVersion || !status.available) return null;
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

// ── Banner over an Office preview ───────────────────────────────────────────

/** localStorage: the renderer version whose install/update offer was hidden. */
const OFFER_HIDDEN_KEY = "evo.officeRuntimeOfferHidden";

function megabytes(bytes: number): string {
  const value = bytes / (1024 * 1024);
  // One decimal below 10 MB so a slow start visibly moves instead of
  // reading "1 MB" from the first byte to the millionth.
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} MB`;
}

function readHiddenVersion(): string | null {
  try {
    return window.localStorage.getItem(OFFER_HIDDEN_KEY);
  } catch {
    return null;
  }
}

function writeHiddenVersion(version: string): void {
  try {
    window.localStorage.setItem(OFFER_HIDDEN_KEY, version);
  } catch {
    // Storage may be unavailable; the offer then only hides for this viewer.
  }
}

const BANNER_PHASE = {
  downloading: "Downloading the exact renderer",
  verifying: "Verifying the download",
  extracting: "Installing the exact renderer",
} as const;

const bannerRow = "flex shrink-0 items-center gap-2 border-b border-border/60 bg-background px-3 py-1.5 text-xs";

/**
 * Offers the optional LibreOffice runtime that renders Office files exactly
 * as laid out, reports its download, and says when an exact render is
 * pending or could not be produced. Nothing is fetched until the person asks;
 * without it the viewer keeps the built-in approximate renderer.
 */
export function OfficeRuntimeBanner({
  rendering,
  fallback,
}: {
  /** The approximate pages are shown while the exact render runs. */
  rendering: boolean;
  /** The exact renderer is installed but could not render this file. */
  fallback: boolean;
}) {
  const { status, act } = useOffice();
  const starting = useOfficeStore((s) => s.pending === "office_install");
  const requestError = useOfficeStore((s) => s.actionError);
  const clearActionError = useOfficeStore((s) => s.clearActionError);
  const [hiddenVersion, setHiddenVersion] = React.useState(readHiddenVersion);
  const job = status?.job;
  const install = () => void act("office_install");

  if (requestError || job?.phase === "failed") {
    const text = job?.phase === "failed" ? job.error : requestError;
    return (
      <div className={bannerRow} role="alert">
        <CircleAlertIcon className="size-3.5 shrink-0 text-destructive" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate text-muted-foreground" title={text ?? undefined}>
          Could not install the exact renderer: {text}
        </span>
        {status?.available && (
          <Button size="xs" variant="outline" onClick={install} disabled={starting}>
            Retry
          </Button>
        )}
        <Button
          size="icon-xs"
          variant="ghost"
          aria-label="Dismiss renderer error"
          className="text-muted-foreground"
          onClick={() => {
            clearActionError();
            if (job?.phase === "failed") void act("office_dismiss_error");
          }}
        >
          <XIcon />
        </Button>
      </div>
    );
  }

  if (job) {
    const percent = job.bytesTotal > 0 ? Math.min(100, Math.round((job.bytesDone / job.bytesTotal) * 100)) : 0;
    const downloading = job.phase === "downloading";
    return (
      <div className="shrink-0 border-b border-border/60 bg-background px-3 py-2" role="status" aria-live="polite">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Spinner className="size-3" />
          <span>{BANNER_PHASE[job.phase]}</span>
          {downloading && (
            <span className="ml-auto tabular-nums">
              {percent}% · {megabytes(job.bytesDone)} / {megabytes(job.bytesTotal)}
            </span>
          )}
          {(downloading || job.phase === "verifying") && (
            <Button
              size="xs"
              variant="outline"
              className={downloading ? undefined : "ml-auto"}
              onClick={() => void act("office_cancel_install")}
            >
              Cancel
            </Button>
          )}
        </div>
        <Progress value={downloading ? percent : 100} aria-label="Exact renderer download" className="mt-1.5 [&_[data-slot=progress-track]]:h-1" />
      </div>
    );
  }

  if (rendering) {
    return (
      <div className={bannerRow} role="status" aria-live="polite">
        <Spinner className="size-3 shrink-0" />
        <span className="text-muted-foreground">Rendering exact pages… the first exact render can take up to a minute.</span>
      </div>
    );
  }

  const installed = status?.installedVersion ?? null;
  const offerVersion = status?.available ? status.version : null;
  // An update outranks the fallback notice: the newer renderer may be the
  // one that can render this file.
  const offered = Boolean(offerVersion) && installed !== offerVersion && hiddenVersion !== offerVersion;

  if (fallback && !offered) {
    return (
      <div className={bannerRow} role="status">
        <CircleAlertIcon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="text-muted-foreground">The exact renderer could not render this file, so this preview is approximate.</span>
      </div>
    );
  }

  if (!status || !offered || !offerVersion) return null;

  const hide = () => {
    writeHiddenVersion(offerVersion);
    setHiddenVersion(offerVersion);
  };

  return (
    <div className={bannerRow}>
      <span className="min-w-0 flex-1 text-muted-foreground">
        {installed
          ? `A newer exact renderer (LibreOffice ${offerVersion}) is available.`
          : `This preview is approximate. Install the LibreOffice renderer${status.downloadBytes ? ` (${megabytes(status.downloadBytes)})` : ""} to see pages exactly as Office lays them out.`}
      </span>
      <Button size="xs" variant="outline" onClick={install} disabled={starting}>
        {installed ? (
          <>
            <RefreshCwIcon aria-hidden="true" /> Update renderer
          </>
        ) : (
          <>
            <DownloadIcon aria-hidden="true" /> Install renderer
          </>
        )}
      </Button>
      <Button size="icon-xs" variant="ghost" aria-label="Hide renderer suggestion" className="text-muted-foreground" onClick={hide}>
        <XIcon />
      </Button>
    </div>
  );
}
