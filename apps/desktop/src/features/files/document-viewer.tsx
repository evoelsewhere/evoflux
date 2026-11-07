import * as React from "react";
import { DownloadIcon, FileTextIcon } from "lucide-react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { OfficeActions, OfficeError, OfficeProgress } from "@/components/office-install";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { formatBytes } from "@/lib/format";
import { useEngineStore } from "@/stores/engine-store";
import { officeReady, useOffice } from "@/stores/office-store";
import { OFFICE_FILE } from "./document-kinds";
import { officeKind } from "./office/kinds";
import { OfficeViewer } from "./office/office-viewer";
import { readBytes } from "./fs";

// Word, PowerPoint and Excel files open in the native Office viewer
// (office/office-viewer.tsx, docs/features/office-v3-parity/spec.md): the
// engine renders them to HTML, or to exact pages with the LibreOffice runtime.
// Legacy and OpenDocument files are shown as pages: the engine
// converts them to a PDF with the LibreOffice runtime (RPC `office_convert`,
// cached), and pdf.js draws the PDF. Plain PDFs skip the conversion.
// docs/features/office/spec.md.

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const PAGE_GAP = 16;
const GUTTER = 32;

interface PageSize {
  width: number;
  height: number;
}

async function pageSizes(doc: PDFDocumentProxy): Promise<PageSize[]> {
  const sizes: PageSize[] = [];
  for (let n = 1; n <= doc.numPages; n++) {
    const view = (await doc.getPage(n)).getViewport({ scale: 1 });
    sizes.push({ width: view.width, height: view.height });
  }
  return sizes;
}

function Page({ doc, number, size, scale }: { doc: PDFDocumentProxy; number: number; size: PageSize; scale: number }) {
  const host = React.useRef<HTMLDivElement>(null);
  const canvas = React.useRef<HTMLCanvasElement>(null);
  const [near, setNear] = React.useState(number <= 2);

  // Draw only pages near the viewport: a long document is hundreds of canvases.
  React.useEffect(() => {
    const element = host.current;
    if (!element) return;
    const observer = new IntersectionObserver((entries) => setNear(entries.some((e) => e.isIntersecting)), { rootMargin: "900px 0px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  React.useEffect(() => {
    if (!near) return;
    let task: { cancel(): void; promise: Promise<unknown> } | undefined;
    let cancelled = false;
    void doc.getPage(number).then((page) => {
      const target = canvas.current;
      if (cancelled || !target) return;
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scale * ratio });
      target.width = Math.floor(viewport.width);
      target.height = Math.floor(viewport.height);
      task = page.render({ canvas: target, viewport });
      task.promise.catch(() => undefined);
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, number, scale, near]);

  const width = size.width * scale;
  const height = size.height * scale;
  return (
    <div ref={host} style={{ width, height }} className="shrink-0 bg-white shadow-[0_0_0_1px_rgb(0_0_0/0.08),0_2px_8px_rgb(0_0_0/0.12)]">
      {near && <canvas ref={canvas} style={{ width, height }} aria-label={`Page ${number}`} />}
    </div>
  );
}

function Pages({ doc }: { doc: PDFDocumentProxy }) {
  const scroller = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);
  const [sizes, setSizes] = React.useState<PageSize[] | null>(null);

  React.useEffect(() => {
    let live = true;
    setSizes(null);
    void pageSizes(doc).then((s) => live && setSizes(s));
    return () => {
      live = false;
    };
  }, [doc]);

  React.useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const available = Math.max(0, width - GUTTER);
  return (
    <div ref={scroller} className="h-full overflow-auto bg-muted/40 py-4">
      <div className="mx-auto flex w-max min-w-full flex-col items-center" style={{ gap: PAGE_GAP }}>
        {sizes &&
          available > 0 &&
          sizes.map((size, index) => (
            // Fit the widest page to the pane (never enlarge past 1.6x), keeping each page's own proportions.
            <Page
              key={index}
              doc={doc}
              number={index + 1}
              size={size}
              scale={Math.min(1.6, available / Math.max(...sizes.map((s) => s.width)))}
            />
          ))}
      </div>
      {sizes && sizes.length > 1 && <p className="pt-4 text-center text-xs text-muted-foreground">{sizes.length} pages</p>}
    </div>
  );
}

type Phase =
  | { kind: "loading"; label: string }
  | { kind: "ready"; doc: PDFDocumentProxy }
  | { kind: "error"; message: string };

export interface DocumentViewerProps {
  path: string;
  /** The file's mtime: a new one re-renders the document. */
  version: number;
  size: number;
  /** The chat's working folder (Office documents: annotations and versions name files relative to it). */
  root: string;
  onOpenExternal(): void;
  /** An Office document started or stopped being built live by the agent (the Files tree steps aside). */
  onLiveDeckChange?(live: boolean): void;
}

/** A document shown as pages: Word, Excel and PowerPoint in the native viewer, the rest through pdf.js. */
export function DocumentViewer({ path, version, size, root, onOpenExternal, onLiveDeckChange }: DocumentViewerProps) {
  const kind = officeKind(path);
  const pages = <PdfPagesViewer path={path} version={version} size={size} onOpenExternal={onOpenExternal} />;
  if (!kind) return pages;
  return (
    <OfficeViewer
      key={path}
      path={path}
      kind={kind}
      root={root}
      size={size}
      mtime={version}
      onLiveDeckChange={onLiveDeckChange}
      legacy={pages}
    />
  );
}

/** LibreOffice pages through pdf.js: PDFs, legacy and OpenDocument files, and Office files on an engine without the native preview. */
function PdfPagesViewer({ path, version, size, onOpenExternal }: { path: string; version: number; size: number; onOpenExternal(): void }) {
  const office = OFFICE_FILE.test(path);
  const { status, error: statusError } = useOffice();
  const ready = officeReady(status);
  const [phase, setPhase] = React.useState<Phase>({ kind: "loading", label: "Opening" });

  React.useEffect(() => {
    if (office && !ready) return;
    let live = true;
    let opened: { destroy(): Promise<void> } | undefined;
    setPhase((old) => (old.kind === "ready" ? old : { kind: "loading", label: office ? "Rendering pages" : "Opening" }));
    void (async () => {
      try {
        let pdfPath = path;
        if (office) {
          const converted = await useEngineStore.getState().request<{ pdf: string }>("office_convert", { path });
          pdfPath = converted.pdf;
        }
        const bytes = await readBytes(pdfPath);
        const loading = pdfjs.getDocument({ data: new Uint8Array(bytes) });
        const doc = await loading.promise;
        if (!live) {
          void loading.destroy();
          return;
        }
        opened = loading;
        setPhase({ kind: "ready", doc });
      } catch (e) {
        if (live) setPhase({ kind: "error", message: String(e).replace(/^Error:\s*/, "") });
      }
    })();
    return () => {
      live = false;
      // The next document replaces this one; free it after the swap.
      const old = opened;
      if (old) setTimeout(() => void old.destroy(), 1000);
    };
  }, [path, version, office, ready]);

  if (office && !ready) {
    // Until the engine has said whether the renderer is installed, do not offer the download.
    if (!status && !statusError) return <Loading label="Opening" />;
    return <NeedsRenderer size={size} offline={!!statusError} />;
  }
  if (phase.kind === "ready") return <Pages doc={phase.doc} />;
  if (phase.kind === "error")
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon />
          </EmptyMedia>
          <EmptyTitle>Could not show this document</EmptyTitle>
          <EmptyDescription className="break-words">{phase.message}</EmptyDescription>
        </EmptyHeader>
        <Button size="sm" variant="outline" onClick={onOpenExternal}>
          Open with default app
        </Button>
      </Empty>
    );
  return <Loading label={phase.label} />;
}

function Loading({ label }: { label: string }) {
  return (
    <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
      <Spinner className="size-4" /> {label}…
    </div>
  );
}

function NeedsRenderer({ size, offline }: { size: number; offline: boolean }) {
  const { status } = useOffice();
  const job = status?.job ?? null;
  return (
    <Empty className="h-full">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <DownloadIcon />
        </EmptyMedia>
        <EmptyTitle>Install the Office renderer to preview this file</EmptyTitle>
        <EmptyDescription>
          {offline
            ? "Open a chat first: the renderer is installed through its engine."
            : status && !status.available
              ? "It is not available for this platform."
              : `A LibreOffice runtime (${formatBytes(status?.downloadBytes ?? 0)}) is downloaded once and checked before use. This file is ${formatBytes(size)}.`}
        </EmptyDescription>
      </EmptyHeader>
      <div className="flex w-64 flex-col items-stretch gap-3">
        {job && job.phase !== "failed" && <OfficeProgress job={job} />}
        <OfficeError job={job} />
        <div className="flex justify-center">
          <OfficeActions />
        </div>
      </div>
    </Empty>
  );
}
