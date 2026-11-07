import * as React from "react";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CircleAlertIcon,
  LayoutGridIcon,
  Maximize2Icon,
  Minimize2Icon,
  MonitorPlayIcon,
  MoveHorizontalIcon,
  NotepadTextIcon,
  PanelLeftIcon,
  PanelsTopLeftIcon,
  PresentationIcon,
  PrinterIcon,
  RefreshCwIcon,
  SearchIcon,
  SquareDashedMousePointerIcon,
  XIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "lucide-react";
import { OfficeRuntimeBanner } from "@/components/office-install";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { useFilesStore } from "@/stores/files-store";
import { useOffice } from "@/stores/office-store";
import { fileName, relativePath } from "../fs";
import { DeckAnnotator } from "./document-annotator";
import { previewItems, slideThumbnailDocument } from "./document-thumbnail";
import { DocumentVersionControls } from "./document-version-controls";
import { FORMAT_META, type OfficeKind } from "./kinds";
import { loadPreview, PreviewUnsupported, type PreviewMode } from "./load-preview";
import { DocumentPreviewSkeleton } from "./preview-skeleton";
import { adjacentCellName, clearSearchMarks, markSearchMatches } from "./search";

// The Files tool's viewer for Word, Excel and PowerPoint files (port of v3
// web/src/components/workspace-document-preview.tsx;
// docs/features/office-v3-parity/sdd.md FR-4, FR-5, FR-8).
//
// Rendering stays in the engine's inert, self-contained HTML document
// (`office_preview`: the native render, or exact pages from the LibreOffice
// runtime) shown in an `<iframe srcDoc sandbox="allow-same-origin">`: no
// script runs in it, and this component scripts its DOM for navigation,
// search, zoom, fit, workbook selection and following a deck being built.

type FitMode = "custom" | "width" | "page";
type PresentationView = "normal" | "sorter" | "reading";
type PresentationWorkspaceView = Exclude<PresentationView, "reading">;

interface NavigatorEntry {
  label: string;
  index: number;
}

interface SelectedCell {
  name: string;
  value: string;
}

interface SlidePreviewMeta {
  notes: string;
  thumbnailHtml: string;
}

interface ViewerKeyEvent {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  target: EventTarget | null;
  preventDefault: () => void;
  stopPropagation?: () => void;
}

interface WebkitFullscreenDocument extends Document {
  webkitExitFullscreen?: () => Promise<void> | void;
  webkitFullscreenElement?: Element | null;
}

interface WebkitFullscreenElement extends HTMLElement {
  webkitRequestFullscreen?: () => Promise<void> | void;
}

export interface OfficeViewerProps {
  /** The file (absolute). */
  path: string;
  kind: OfficeKind;
  /** The chat's working folder: annotations and versions name the file relative to it. */
  root: string;
  size: number;
  /** The file's mtime: a new one re-renders it. */
  mtime: number;
  /** A deck or workbook started or stopped being built live by the agent. */
  onLiveDeckChange?(live: boolean): void;
  /** Shown instead when the engine predates the native preview (LibreOffice pages). */
  legacy: React.ReactNode;
}

function clampZoom(value: number): number {
  return Math.min(300, Math.max(25, Math.round(value)));
}

function slideNotes(element: HTMLElement): string {
  const inlineNotes = element.dataset.previewNotes?.trim();
  if (inlineNotes) return inlineNotes;
  return element.querySelector<HTMLElement>("[data-preview-notes]")?.textContent?.trim() ?? "";
}

function errorText(reason: unknown): string {
  return (reason instanceof Error ? reason.message : String(reason)).replace(/^Error:\s*/, "");
}

function SlideThumbnail({ html, label }: { html?: string; label: string }) {
  if (!html) {
    return (
      <span className="flex h-full w-full items-center justify-center bg-white text-[#b7472a]">
        <PresentationIcon className="size-4.5" aria-hidden="true" />
      </span>
    );
  }
  return (
    <iframe
      srcDoc={html}
      title={label}
      sandbox=""
      referrerPolicy="no-referrer"
      loading="lazy"
      tabIndex={-1}
      aria-hidden="true"
      className="pointer-events-none h-full w-full border-0 bg-white"
    />
  );
}

const toolbarButtonClass =
  "flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-30 [&_svg]:size-3.5";
const pressedClass = "bg-accent text-foreground";
const annotateClass = "bg-brand/12 text-brand hover:bg-brand/16 hover:text-brand";
const footerButtonClass =
  "flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-accent [&_svg]:size-3.25";
const readingButtonClass =
  "flex size-10 items-center justify-center rounded-full bg-black/55 text-white shadow-lg backdrop-blur-sm transition hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white";

/**
 * Host-owned reader shell for every generated document format: the
 * document renders in the engine, navigation and selection happen here.
 */
export function OfficeViewer({ path, kind, root, size, mtime, onLiveDeckChange, legacy }: OfficeViewerProps) {
  const meta = FORMAT_META[kind];
  const name = fileName(path);
  const relPath = root ? relativePath(root, path) : path;
  const chatId = useEngineStore((s) => s.activeId);
  const engineStatus = useEngineStore((s) => s.status);
  const engineReady = engineStatus === "ready";
  // Whether the chat's turn runs: a deck renders live only meanwhile, and sent annotations shimmer.
  const agentWorking = useEngineStore((s) => s.transcript.busy);
  const { status: officeStatus, error: officeStatusError } = useOffice();
  // Once LibreOffice is installed the engine renders Office files exactly;
  // the key changes so an open preview re-renders the moment it lands.
  const exactRenderer = officeStatus?.installedVersion ?? "";
  // Until the engine said whether the runtime is installed, wait: the key would change right away.
  const statusKnown = !!officeStatus || !!officeStatusError;
  const documentKey = `${path}:${size}:${mtime}`;
  // A deck renders live only while this chat's turn runs, so a turn
  // starting or ending re-renders it even when the file did not change
  // (an interrupted build falls back to its finished slides).
  // Decks and workbooks can be built live, slide by slide or sheet by sheet.
  const liveBuildable = kind === "pptx" || kind === "xlsx";
  const turnKey = liveBuildable ? String(agentWorking) : "";
  const [annotating, setAnnotating] = React.useState(false);
  // A workbook shows its cell grid (the native render) by default; the
  // exact renderer's pages are print layout, a toggle away. Selecting cells
  // always needs the grid.
  const [printLayout, setPrintLayout] = React.useState(false);
  const gridMode = kind === "xlsx" && (!printLayout || annotating);
  const requestKey = `${documentKey}:${exactRenderer}:${turnKey}:${gridMode ? "grid" : ""}`;
  const mode: PreviewMode = gridMode ? "native" : kind === "xlsx" ? "exact" : "auto";

  const iframeRef = React.useRef<HTMLIFrameElement>(null);
  const viewerRef = React.useRef<HTMLElement>(null);
  const itemElementsRef = React.useRef<HTMLElement[]>([]);
  const activeIndexRef = React.useRef(0);
  const fullscreenActiveRef = React.useRef(false);
  const readingReturnViewRef = React.useRef<PresentationWorkspaceView>("normal");
  const frameCleanupRef = React.useRef<(() => void) | null>(null);
  const selectedCellElementRef = React.useRef<HTMLElement | null>(null);
  const viewerKeyDownRef = React.useRef<(event: ViewerKeyEvent) => void>(() => undefined);
  const viewedSourceRef = React.useRef<string | null>(null);
  // While the agent builds a deck the viewer follows the slide being built,
  // until the person scrolls, clicks or navigates themselves.
  const followLiveRef = React.useRef(true);
  // Whether the frame last showed a deck still being built.
  const deckLiveRef = React.useRef(false);
  // The slide a deck under construction is followed to (-1: not live).
  const liveTargetRef = React.useRef(-1);
  // Which renderer drew the frame last (null: nothing shown yet).
  const frameRendererRef = React.useRef<string | null>(null);
  const savedScrollRef = React.useRef(0);
  // The layout a live build collapsed, restored once the deck is finished
  // unless the person reopened the thumbnails in the meantime.
  const liveLayoutRef = React.useRef({ live: false, restoreNavigator: false });
  const onLiveDeckChangeRef = React.useRef(onLiveDeckChange);
  const navigatorOpenRef = React.useRef(false);
  const [result, setResult] = React.useState<{ key: string; html?: string; error?: string } | null>(null);
  const [unsupported, setUnsupported] = React.useState(false);
  const [retryKey, setRetryKey] = React.useState(0);
  // Slide thumbnails start hidden: the deck scrolls like a document and the
  // viewer gets the full width; the toolbar button shows them.
  const [navigatorOpen, setNavigatorOpen] = React.useState(false);
  const [entries, setEntries] = React.useState<NavigatorEntry[]>([]);
  const [activeIndex, setActiveIndex] = React.useState(0);
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState("");
  const [searchCount, setSearchCount] = React.useState(0);
  const [searchIndex, setSearchIndex] = React.useState(0);
  const [zoom, setZoom] = React.useState(100);
  // The zoom a reloaded frame gets back when it is not refitted.
  const zoomRef = React.useRef(100);
  const initialFitMode: FitMode = kind === "pptx" ? "page" : kind === "xlsx" ? "custom" : "width";
  const [fitMode, setFitMode] = React.useState<FitMode>(initialFitMode);
  const [selectedCell, setSelectedCell] = React.useState<SelectedCell | null>(null);
  const [presentationView, setPresentationView] = React.useState<PresentationView>("normal");
  const [notesOpen, setNotesOpen] = React.useState(false);
  const [isFullscreen, setIsFullscreen] = React.useState(false);
  const [slidePreviewMeta, setSlidePreviewMeta] = React.useState<SlidePreviewMeta[]>([]);
  const [slideAspectRatio, setSlideAspectRatio] = React.useState("16 / 9");
  const [lastGood, setLastGood] = React.useState<{ source: string; renderer: string; html: string } | null>(null);
  const freshResult = result?.key === `${requestKey}:${retryKey}` ? result : null;
  // Keep showing this file's last good pages while a newer version renders —
  // the agent saving a deck slide by slide, or the exact renderer landing —
  // and when a save was read mid-write, instead of flashing a loader or error.
  const reusable = lastGood?.source === path ? lastGood : null;
  const staleResult = !freshResult?.html && reusable ? { key: `stale:${path}`, html: reusable.html } : null;
  const currentResult = freshResult?.html ? freshResult : (staleResult ?? freshResult);
  const renderingExact = Boolean(staleResult && reusable && reusable.renderer !== exactRenderer);
  const exactFallback = Boolean(
    exactRenderer &&
      freshResult?.html &&
      !freshResult.html.includes('data-preview-renderer="libreoffice-') &&
      // A deck the agent is still building renders natively on purpose; the
      // exact render follows once it is finished.
      !freshResult.html.includes('data-deck-live="true"') &&
      // So does a workbook's cell grid.
      !gridMode,
  );
  const isPresentation = kind === "pptx";
  // With the slide thumbnails collapsed, a deck reads top to bottom like a
  // document: every slide is laid out and the frame scrolls between them.
  const slideScroll = isPresentation && presentationView === "normal" && !(navigatorOpen && entries.length > 1);
  const slideScrollRef = React.useRef(slideScroll);
  const fullscreenSupported =
    typeof Element !== "undefined" &&
    Boolean(Element.prototype.requestFullscreen || (HTMLElement.prototype as WebkitFullscreenElement).webkitRequestFullscreen);
  const hasSlideNotes = slidePreviewMeta.some((slide) => Boolean(slide.notes));
  const activeSlideNotes = slidePreviewMeta[activeIndex]?.notes;

  React.useEffect(() => {
    if (!engineReady || !statusKnown) return;
    let cancelled = false;
    const key = `${requestKey}:${retryKey}`;
    void loadPreview(path, kind, mode, name)
      .then(({ html }) => {
        if (cancelled) return;
        // Reset the view for a different file only; a refresh of the same
        // file keeps zoom, layout and the current slide.
        if (viewedSourceRef.current !== path) {
          viewedSourceRef.current = path;
          followLiveRef.current = true;
          deckLiveRef.current = false;
          frameRendererRef.current = null;
          savedScrollRef.current = 0;
          setPresentationView("normal");
          setNotesOpen(false);
          setSlidePreviewMeta([]);
          setSlideAspectRatio("16 / 9");
          setZoom(100);
          zoomRef.current = 100;
          setFitMode(initialFitMode);
        } else if (!deckLiveRef.current && html.includes('data-deck-live="true"')) {
          // The agent started building this deck again: follow it again.
          followLiveRef.current = true;
        }
        // A deck the agent is building gets the whole surface: the thumbnails
        // collapse (so the slides scroll and the viewer follows the one being
        // built) and the host is told, so it can hide its own chrome too.
        const live = liveBuildable && html.includes('data-deck-live="true"');
        const layout = liveLayoutRef.current;
        if (live !== layout.live) {
          layout.live = live;
          onLiveDeckChangeRef.current?.(live);
          if (live) {
            layout.restoreNavigator = navigatorOpenRef.current;
            setNavigatorOpen(false);
          } else if (layout.restoreNavigator) {
            layout.restoreNavigator = false;
            setNavigatorOpen(true);
          }
        }
        setResult({ key, html });
        setLastGood({ source: path, renderer: exactRenderer, html });
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        if (reason instanceof PreviewUnsupported) {
          setUnsupported(true);
          return;
        }
        setResult({ key, error: errorText(reason) });
      });
    return () => {
      cancelled = true;
    };
    // `requestKey` stands for path, size, mtime, renderer, turn and grid.
  }, [engineReady, statusKnown, requestKey, retryKey]);

  React.useEffect(() => () => frameCleanupRef.current?.(), []);

  React.useEffect(() => {
    onLiveDeckChangeRef.current = onLiveDeckChange;
  }, [onLiveDeckChange]);

  React.useEffect(() => {
    navigatorOpenRef.current = navigatorOpen;
  }, [navigatorOpen]);

  React.useEffect(
    () => () => {
      if (liveLayoutRef.current.live) onLiveDeckChangeRef.current?.(false);
    },
    [],
  );

  React.useEffect(() => {
    if (!window.matchMedia) return;
    const mobileViewport = window.matchMedia("(max-width: 640px)");
    const handleViewportChange = (event: MediaQueryListEvent) => {
      if (event.matches) setNavigatorOpen(false);
    };
    mobileViewport.addEventListener("change", handleViewportChange);
    return () => mobileViewport.removeEventListener("change", handleViewportChange);
  }, []);

  React.useEffect(() => {
    const fullscreenDocument = document as WebkitFullscreenDocument;
    const handleFullscreenChange = () => {
      const fullscreenElement = fullscreenDocument.fullscreenElement ?? fullscreenDocument.webkitFullscreenElement ?? null;
      const active = fullscreenElement === viewerRef.current;
      const wasActive = fullscreenActiveRef.current;
      fullscreenActiveRef.current = active;
      setIsFullscreen(active);
      if (wasActive && !active) {
        setPresentationView((view) => (view === "reading" ? readingReturnViewRef.current : view));
      }
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    document.addEventListener("webkitfullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      document.removeEventListener("webkitfullscreenchange", handleFullscreenChange);
    };
  }, []);

  const applyZoom = React.useCallback((nextZoom: number, fit: FitMode = "custom") => {
    const value = clampZoom(nextZoom);
    const frameDocument = iframeRef.current?.contentDocument;
    frameDocument?.body?.style.setProperty("zoom", String(value / 100));
    zoomRef.current = value;
    setZoom(value);
    setFitMode(fit);
  }, []);

  const fitDocument = React.useCallback(
    (fit: Exclude<FitMode, "custom">) => {
      const frame = iframeRef.current;
      const frameDocument = frame?.contentDocument;
      const target = itemElementsRef.current[activeIndexRef.current] ?? itemElementsRef.current[0];
      if (!frame || !frameDocument?.body || !target) return;

      frameDocument.body.style.setProperty("zoom", "1");
      const fitWidth = Number(target.dataset.previewFitWidth);
      const fitHeight = Number(target.dataset.previewFitHeight);
      const width =
        Number.isFinite(fitWidth) && fitWidth > 0 ? fitWidth : Math.max(target.scrollWidth, target.getBoundingClientRect().width);
      const height =
        Number.isFinite(fitHeight) && fitHeight > 0 ? fitHeight : Math.max(target.scrollHeight, target.getBoundingClientRect().height);
      const widthScale = (frame.clientWidth - 32) / Math.max(width, 1);
      const heightScale = (frame.clientHeight - 32) / Math.max(height, 1);
      const scale = fit === "page" ? Math.min(widthScale, heightScale) : widthScale;
      // Fitting shrinks a page or sheet to the view but never blows it up past
      // its real size; slides scale up to fill the view, as in PowerPoint.
      applyZoom((kind === "pptx" ? scale : Math.min(scale, 1)) * 100, fit);
    },
    [applyZoom, kind],
  );

  const selectSpreadsheetCell = React.useCallback((target: HTMLElement, focus = false) => {
    const frameDocument = target.ownerDocument;
    selectedCellElementRef.current?.removeAttribute("data-evo-selected-cell");
    if (selectedCellElementRef.current) selectedCellElementRef.current.tabIndex = -1;
    frameDocument.querySelectorAll<HTMLElement>("[data-evo-selected-header]").forEach((header) => {
      header.removeAttribute("data-evo-selected-header");
    });

    target.setAttribute("data-evo-selected-cell", "true");
    target.tabIndex = 0;
    selectedCellElementRef.current = target;
    const coordinate = target.dataset.cell ?? "";
    const coordinateParts = /^([A-Z]+)([1-9]\d*)$/.exec(coordinate);
    const surface = target.closest<HTMLElement>("[data-preview-item]");
    if (coordinateParts && surface) {
      surface.querySelector<HTMLElement>(`[data-column="${coordinateParts[1]}"]`)?.setAttribute("data-evo-selected-header", "true");
      surface.querySelector<HTMLElement>(`[data-row="${coordinateParts[2]}"]`)?.setAttribute("data-evo-selected-header", "true");
    }
    setSelectedCell({
      name: coordinate,
      value: target.dataset.formula ?? target.dataset.displayValue ?? target.textContent?.trim() ?? "",
    });
    if (focus) target.focus();
  }, []);

  React.useEffect(() => {
    if (fitMode === "custom") return;
    const handleResize = () => {
      fitDocument(fitMode);
      // Refitting moves the slides; a followed deck keeps the slide being
      // built in view (the panel resizing as the build starts, for example).
      const target = itemElementsRef.current[liveTargetRef.current];
      if (followLiveRef.current && slideScrollRef.current && target) {
        target.scrollIntoView?.({ block: "center" });
      }
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(handleResize);
    if (iframeRef.current) observer?.observe(iframeRef.current);
    window.addEventListener("resize", handleResize);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", handleResize);
    };
  }, [currentResult?.html, fitDocument, fitMode]);

  const goToItem = React.useCallback(
    (index: number) => {
      const normalized = Math.max(0, Math.min(index, itemElementsRef.current.length - 1));
      // Navigating away stops following a deck being built; going back to
      // the slide it follows picks the build up again.
      followLiveRef.current = liveTargetRef.current >= 0 && normalized === liveTargetRef.current;
      const singleSurface = kind === "xlsx" || (kind === "pptx" && !slideScrollRef.current);
      itemElementsRef.current.forEach((item, itemIndex) => {
        if (singleSurface) item.toggleAttribute("hidden", itemIndex !== normalized);
        else item.removeAttribute("hidden");
      });
      itemElementsRef.current[normalized]?.scrollIntoView?.({
        behavior: singleSurface ? "auto" : "smooth",
        block: "start",
      });
      activeIndexRef.current = normalized;
      setActiveIndex(normalized);
      if (kind === "xlsx") {
        const firstCell = itemElementsRef.current[normalized]?.querySelector<HTMLElement>("[data-cell]");
        if (firstCell) selectSpreadsheetCell(firstCell);
        else setSelectedCell(null);
      }
      if (fitMode !== "custom") {
        iframeRef.current?.contentWindow?.requestAnimationFrame(() => fitDocument(fitMode));
      }
    },
    [fitDocument, fitMode, kind, selectSpreadsheetCell],
  );

  React.useEffect(() => {
    if (!isPresentation || presentationView === "sorter") return;
    const frameWindow = iframeRef.current?.contentWindow;
    frameWindow?.requestAnimationFrame(() => fitDocument(presentationView === "reading" || fitMode === "custom" ? "page" : fitMode));
  }, [fitDocument, fitMode, isPresentation, presentationView]);

  const exitFullscreen = React.useCallback(async () => {
    const fullscreenDocument = document as WebkitFullscreenDocument;
    try {
      if (fullscreenDocument.exitFullscreen) await fullscreenDocument.exitFullscreen();
      else await fullscreenDocument.webkitExitFullscreen?.();
    } catch {
      // Reading View remains usable when the host denies the Fullscreen API.
    }
  }, []);

  const exitReadingView = React.useCallback(() => {
    setPresentationView(readingReturnViewRef.current);
    if (fullscreenActiveRef.current) void exitFullscreen();
    requestAnimationFrame(() => viewerRef.current?.focus());
  }, [exitFullscreen]);

  const handleViewerKeyDown = React.useCallback(
    (event: ViewerKeyEvent) => {
      const targetTag = (event.target as { tagName?: string } | null)?.tagName;
      if (targetTag === "INPUT" || targetTag === "TEXTAREA") return;
      if (isPresentation && presentationView === "reading" && event.key === "Escape") {
        event.preventDefault();
        exitReadingView();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "f") {
        event.preventDefault();
        // Not the app's Ctrl+F (open Files): it is already open.
        event.stopPropagation?.();
        setSearchOpen(true);
        return;
      }
      // Ctrl/⌘ with +, = or − zooms the app (its own shortcut), not the document.
      if ((event.ctrlKey || event.metaKey) && ["+", "=", "-"].includes(event.key)) return;
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        applyZoom(zoom + 10);
        return;
      }
      if (event.key === "-") {
        event.preventDefault();
        applyZoom(zoom - 10);
        return;
      }

      const singleSurface = kind === "pptx" || kind === "xlsx";
      const previous = event.key === "PageUp" || (singleSurface && (event.key === "ArrowLeft" || event.key === "ArrowUp"));
      const next =
        event.key === "PageDown" ||
        (kind === "pptx" && event.key === " " && targetTag !== "BUTTON") ||
        (singleSurface && (event.key === "ArrowRight" || event.key === "ArrowDown"));
      if (previous || next) {
        event.preventDefault();
        goToItem(activeIndexRef.current + (previous ? -1 : 1));
      } else if (event.key === "Home") {
        event.preventDefault();
        goToItem(0);
      } else if (event.key === "End") {
        event.preventDefault();
        goToItem(itemElementsRef.current.length - 1);
      }
    },
    [applyZoom, exitReadingView, goToItem, isPresentation, kind, presentationView, zoom],
  );

  React.useEffect(() => {
    viewerKeyDownRef.current = handleViewerKeyDown;
  }, [handleViewerKeyDown]);

  const selectSearchMatch = React.useCallback(
    (index: number) => {
      const frameDocument = iframeRef.current?.contentDocument;
      const marks = frameDocument ? Array.from(frameDocument.querySelectorAll<HTMLElement>("mark[data-evo-search]")) : [];
      if (marks.length === 0) {
        setSearchIndex(0);
        return;
      }
      const normalized = (index + marks.length) % marks.length;
      marks.forEach((mark, markIndex) => {
        mark.style.background = markIndex === normalized ? "#fbbf24" : "#fde68a";
        mark.style.outline = markIndex === normalized ? "2px solid #d97706" : "";
      });
      const active = marks[normalized];
      const itemIndex = itemElementsRef.current.findIndex((item) => item.contains(active));
      if (itemIndex >= 0) goToItem(itemIndex);
      active.scrollIntoView?.({ behavior: "smooth", block: "center" });
      setSearchIndex(normalized);
    },
    [goToItem],
  );

  const refreshSearch = React.useCallback(
    (query: string) => {
      const frameDocument = iframeRef.current?.contentDocument;
      if (!frameDocument) return;
      const matches = markSearchMatches(frameDocument, query);
      setSearchCount(matches.length);
      setSearchIndex(0);
      if (matches.length > 0) {
        matches[0].style.background = "#fbbf24";
        matches[0].style.outline = "2px solid #d97706";
        const itemIndex = itemElementsRef.current.findIndex((item) => item.contains(matches[0]));
        if (itemIndex >= 0) goToItem(itemIndex);
        matches[0].scrollIntoView?.({ block: "center" });
      }
    },
    [goToItem],
  );

  const closeSearch = React.useCallback(() => {
    setSearchOpen(false);
    setSearchQuery("");
    setSearchCount(0);
    setSearchIndex(0);
    const frameDocument = iframeRef.current?.contentDocument;
    if (frameDocument) clearSearchMarks(frameDocument);
  }, []);

  const handleFrameLoad = React.useCallback(() => {
    frameCleanupRef.current?.();
    frameCleanupRef.current = null;
    const frame = iframeRef.current;
    const frameDocument = frame?.contentDocument;
    const frameWindow = frame?.contentWindow;
    if (!frame || !frameDocument || !frameWindow) return;

    const elements = previewItems(frameDocument);
    itemElementsRef.current = elements;
    setEntries(
      elements.map((element, index) => ({
        index,
        label: element.dataset.previewLabel || `${kind === "xlsx" ? "Sheet" : kind === "pptx" ? "Slide" : "Page"} ${index + 1}`,
      })),
    );
    if (kind === "pptx") {
      setSlidePreviewMeta(
        elements.map((element) => ({
          notes: slideNotes(element),
          thumbnailHtml: slideThumbnailDocument(frameDocument, element),
        })),
      );
      const renderedSlide = elements[0]?.querySelector<HTMLElement>(".slide");
      setSlideAspectRatio(renderedSlide?.style.aspectRatio || "16 / 9");
    } else {
      setSlidePreviewMeta([]);
    }
    const continuousSlides = kind === "pptx" && slideScrollRef.current;
    // A deck being built: follow the slide being built (or, one slide at a
    // time, the latest finished one) until the person takes over.
    const liveDeck = liveBuildable && Boolean(frameDocument.querySelector("[data-deck-live]"));
    const statuses = elements.map((element) => element.dataset.slideStatus ?? "");
    const building = statuses.indexOf("building");
    const lastDone = statuses.lastIndexOf("done");
    const followTarget = continuousSlides ? (building >= 0 ? building : lastDone) : lastDone >= 0 ? lastDone : building;
    // The save that finishes a followed deck lands on its last slide.
    const justFinished = liveBuildable && !liveDeck && deckLiveRef.current && followLiveRef.current;
    deckLiveRef.current = liveDeck;
    liveTargetRef.current = liveDeck ? followTarget : -1;
    const renderer = frameDocument.querySelector("[data-preview-renderer]")?.getAttribute("data-preview-renderer") ?? "native";
    const rendererChanged = frameRendererRef.current !== null && frameRendererRef.current !== renderer;
    frameRendererRef.current = renderer;
    const following = justFinished || (liveDeck && followLiveRef.current && followTarget >= 0);
    const restoredIndex = justFinished
      ? elements.length - 1
      : following
        ? followTarget
        : Math.max(0, Math.min(activeIndexRef.current, elements.length - 1));
    activeIndexRef.current = restoredIndex;
    setActiveIndex(restoredIndex);
    frameDocument.documentElement.toggleAttribute("data-evo-continuous", continuousSlides);
    if ((kind === "pptx" && !continuousSlides) || kind === "xlsx") {
      elements.forEach((element, index) => element.toggleAttribute("hidden", index !== restoredIndex));
    }

    const style = frameDocument.createElement("style");
    style.dataset.evoViewer = "true";
    style.textContent = `
      [data-evo-selected-cell] { outline: 2px solid #107c41 !important; outline-offset: -2px; }
      [data-evo-selected-header] { background: #dcefe4 !important; color: #145c35 !important; font-weight: 600 !important; }
      mark[data-evo-search] { scroll-margin: 72px; }
      [data-preview-item] { scroll-margin-top: 18px; }
      [data-preview-notes]:not([data-preview-item]) { display: none !important; }
      ${
        kind === "pptx"
          ? `
        html, body { height: 100%; overflow: hidden !important; background: var(--evo-stage-background, #e8eaed) !important; }
        body { display: flex !important; align-items: center; justify-content: center; padding: 18px !important; }
        [data-preview-item] { margin: 0 !important; }
        .slide-number { display: none !important; }
        html[data-evo-continuous] { height: 100% !important; overflow: auto !important; }
        html[data-evo-continuous] body {
          height: auto !important; min-height: 100%; overflow: visible !important;
          flex-direction: column; justify-content: flex-start !important;
        }
        html[data-evo-continuous] [data-preview-item] { flex: none; box-shadow: 0 1px 3px #0000002e, 0 6px 18px #0000001f; }
        /* Pages may sit inside a wrapper (exact renders), so space siblings. */
        html[data-evo-continuous] [data-preview-item] ~ [data-preview-item] { margin-top: 28px !important; }
      `
          : ""
      }
    `;
    frameDocument.head?.append(style);

    let scrollFrame = 0;
    const handleScroll = () => {
      if (kind === "pptx" && !slideScrollRef.current) return;
      savedScrollRef.current = frameWindow.scrollY;
      frameWindow.cancelAnimationFrame(scrollFrame);
      scrollFrame = frameWindow.requestAnimationFrame(() => {
        let closest = 0;
        let distance = Number.POSITIVE_INFINITY;
        elements.forEach((element, index) => {
          const currentDistance = Math.abs(element.getBoundingClientRect().top - 16);
          if (currentDistance < distance) {
            closest = index;
            distance = currentDistance;
          }
        });
        // At the end of the document the last page or slide is the current
        // one, even when it is too short to reach the top of the view.
        const rootElement = frameWindow.document.documentElement;
        if (frameWindow.scrollY > 0 && frameWindow.scrollY + frameWindow.innerHeight >= rootElement.scrollHeight - 2) {
          closest = elements.length - 1;
        }
        activeIndexRef.current = closest;
        setActiveIndex(closest);
        // Scrolling back to the slide being built picks the build up again,
        // like a chat that sticks to its newest message.
        const target = elements[liveTargetRef.current];
        if (liveDeck && !followLiveRef.current && target) {
          const box = target.getBoundingClientRect();
          const viewport = frameWindow.innerHeight;
          if (box.top < viewport * 0.75 && box.bottom > viewport * 0.25) followLiveRef.current = true;
        }
      });
    };
    const tracksContinuousScroll = kind === "docx" || kind === "pptx";
    if (tracksContinuousScroll) frameWindow.addEventListener("scroll", handleScroll, { passive: true });
    const handleFrameKeyDown = (event: KeyboardEvent) => viewerKeyDownRef.current(event);
    frameWindow.addEventListener("keydown", handleFrameKeyDown);

    const cells = kind === "xlsx" ? Array.from(frameDocument.querySelectorAll<HTMLElement>("[data-cell]")) : [];
    cells.forEach((cell, index) => {
      cell.setAttribute("role", "gridcell");
      cell.tabIndex = index === 0 ? 0 : -1;
    });
    frameDocument.querySelectorAll<HTMLElement>("table").forEach((table) => {
      if (table.querySelector("[data-cell]")) table.setAttribute("role", "grid");
    });
    const cellFromEvent = (event: Event) => {
      const eventTarget = event.target as Element | null;
      return eventTarget?.closest?.<HTMLElement>("[data-cell]") ?? null;
    };
    const handleCellClick = (event: Event) => {
      if (kind !== "xlsx") return;
      const target = cellFromEvent(event);
      if (!target) return;
      selectSpreadsheetCell(target, true);
    };
    const handleCellFocus = (event: Event) => {
      const target = cellFromEvent(event);
      if (target) selectSpreadsheetCell(target);
    };
    const handleCellKeyDown = (event: KeyboardEvent) => {
      const target = cellFromEvent(event);
      if (!target) return;
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      // Keep spreadsheet arrows inside the grid. Without stopping propagation,
      // the frame-level shortcut also treats them as sheet navigation.
      event.preventDefault();
      event.stopPropagation();
      const nextName = adjacentCellName(target.dataset.cell ?? "", event.key);
      if (!nextName) return;
      const surface = target.closest<HTMLElement>("[data-preview-item]");
      const next = Array.from(surface?.querySelectorAll<HTMLElement>("[data-cell]") ?? []).find((cell) => cell.dataset.cell === nextName);
      if (!next) return;
      selectSpreadsheetCell(next, true);
    };
    frameDocument.addEventListener("click", handleCellClick);
    frameDocument.addEventListener("focusin", handleCellFocus);
    frameDocument.addEventListener("keydown", handleCellKeyDown);
    const initialCell = elements[restoredIndex]?.querySelector<HTMLElement>("[data-cell]");
    if (initialCell) selectSpreadsheetCell(initialCell);

    // Any deliberate interaction hands control back to the person.
    const stopFollowing = () => {
      followLiveRef.current = false;
    };
    if (liveDeck) {
      frameWindow.addEventListener("wheel", stopFollowing, { passive: true });
      frameDocument.addEventListener("pointerdown", stopFollowing);
      frameDocument.addEventListener("keydown", stopFollowing);
    }

    frameCleanupRef.current = () => {
      frameWindow.cancelAnimationFrame(scrollFrame);
      if (tracksContinuousScroll) frameWindow.removeEventListener("scroll", handleScroll);
      frameWindow.removeEventListener("wheel", stopFollowing);
      frameDocument.removeEventListener("pointerdown", stopFollowing);
      frameDocument.removeEventListener("keydown", stopFollowing);
      frameWindow.removeEventListener("keydown", handleFrameKeyDown);
      frameDocument.removeEventListener("click", handleCellClick);
      frameDocument.removeEventListener("focusin", handleCellFocus);
      frameDocument.removeEventListener("keydown", handleCellKeyDown);
      style.remove();
    };

    if (searchQuery) refreshSearch(searchQuery);
    frameWindow.requestAnimationFrame(() => {
      // A workbook keeps its zoom (100% at first): sheets scroll, they are
      // not squeezed to the view.
      if (kind === "xlsx" && fitMode === "custom") applyZoom(zoomRef.current);
      else fitDocument(fitMode === "custom" ? "width" : fitMode);
      if (tracksContinuousScroll && (kind !== "pptx" || continuousSlides)) {
        // A refreshed document keeps its place; a followed deck moves on. A
        // new renderer (the exact render replacing the native one) lays pages
        // out differently, so it keeps the page rather than the pixel offset.
        if (following) elements[restoredIndex]?.scrollIntoView?.({ block: "center", behavior: "smooth" });
        else if (rendererChanged) elements[restoredIndex]?.scrollIntoView?.({ block: "start" });
        else if (savedScrollRef.current) frameWindow.scrollTo(0, savedScrollRef.current);
      }
    });
  }, [applyZoom, fitDocument, fitMode, kind, liveBuildable, refreshSearch, searchQuery, selectSpreadsheetCell]);

  // Switch an already loaded deck between one-slide and scrolling layouts
  // when the thumbnails are shown or collapsed, keeping the current slide.
  React.useEffect(() => {
    // Frame callbacks (load, scroll, navigation) read the layout from here.
    slideScrollRef.current = slideScroll;
    if (!isPresentation) return;
    const frameWindow = iframeRef.current?.contentWindow;
    const frameDocument = iframeRef.current?.contentDocument;
    const items = itemElementsRef.current;
    if (!frameWindow || !frameDocument?.documentElement || items.length === 0) return;
    frameDocument.documentElement.toggleAttribute("data-evo-continuous", slideScroll);
    items.forEach((item, index) => {
      item.toggleAttribute("hidden", !slideScroll && index !== activeIndexRef.current);
    });
    frameWindow.requestAnimationFrame(() => {
      if (slideScroll) items[activeIndexRef.current]?.scrollIntoView?.({ block: "start" });
    });
  }, [isPresentation, slideScroll]);

  React.useEffect(() => {
    if (!isPresentation) return;
    const frameDocument = iframeRef.current?.contentDocument;
    const background = presentationView === "reading" ? "#111111" : "#e8eaed";
    // A frame still swapping in a new srcDoc has no documentElement yet.
    frameDocument?.documentElement?.style.setProperty("--evo-stage-background", background);
    frameDocument?.body?.style.setProperty("--evo-stage-background", background);
  }, [currentResult?.html, isPresentation, presentationView]);

  if (unsupported) return <>{legacy}</>;

  // Documents are rendered by the chat's engine: without one there is nothing to ask.
  const engineMissing = !chatId || engineStatus === "exited" || engineStatus === "error";
  const shownError =
    freshResult?.error && !staleResult
      ? freshResult.error
      : !currentResult?.html && engineMissing
        ? "Open a chat first: its engine renders the document."
        : null;
  if (shownError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <span className="flex size-10 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <CircleAlertIcon className="size-4.5" aria-hidden="true" />
        </span>
        <div>
          <p className="text-sm font-medium text-foreground">Document preview unavailable</p>
          <p className="mt-1 max-w-sm text-xs leading-5 break-words text-muted-foreground">{shownError}</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setRetryKey((value) => value + 1)}>
          <RefreshCwIcon aria-hidden="true" /> Try again
        </Button>
      </div>
    );
  }

  if (!currentResult?.html) {
    return (
      <DocumentPreviewSkeleton
        kind={kind}
        label={meta.label}
        note={exactRenderer ? "The first exact render can take up to a minute." : undefined}
      />
    );
  }

  const runtimeBanner = presentationView !== "reading" && <OfficeRuntimeBanner rendering={renderingExact} fallback={exactFallback} />;

  const itemName = kind === "xlsx" ? "Sheet" : kind === "pptx" ? "Slide" : "Page";
  const itemCount = entries.length;
  const status = itemCount > 0 ? `${itemName} ${activeIndex + 1} of ${itemCount}` : `${meta.label} document`;
  const hasNavigator = kind !== "xlsx" && itemCount > 1;
  const navigatorVisible = hasNavigator && navigatorOpen && (!isPresentation || presentationView === "normal");
  // Versions and annotations belong to the chat's documents; in evo every
  // chat has them (v3 limited them to Work sessions).
  const sessionDocument = Boolean(chatId);
  const deckBeingBuilt = Boolean(currentResult?.html?.includes('data-deck-live="true"'));
  const canAnnotate =
    sessionDocument && ((isPresentation && presentationView === "normal") || kind === "xlsx") && !deckBeingBuilt && Boolean(currentResult?.html);
  const annotateActive = annotating && canAnnotate;
  // Undo, redo and restore write the file: pick the new version up now rather than at the next poll.
  const versionChanged = () => {
    const files = useFilesStore.getState();
    if (files.files[path]) void files.checkDisk(path);
  };

  const enterReadingView = () => {
    readingReturnViewRef.current = presentationView === "sorter" ? "sorter" : "normal";
    setPresentationView("reading");
    setNotesOpen(false);
    requestAnimationFrame(() => viewerRef.current?.focus());
  };

  const toggleFullscreen = async () => {
    if (isFullscreen) {
      await exitFullscreen();
      return;
    }
    const viewer = viewerRef.current as WebkitFullscreenElement | null;
    try {
      if (viewer?.requestFullscreen) await viewer.requestFullscreen();
      else await viewer?.webkitRequestFullscreen?.();
    } catch {
      // Fullscreen is optional; keep the in-window Reading View as the fallback.
    }
  };

  const searchBox = (compact: boolean) => (
    <div className="flex min-w-0 items-center rounded-md bg-background shadow-[0_0_0_1px_var(--border)]">
      <input
        autoFocus
        value={searchQuery}
        onChange={(event) => {
          const query = event.target.value;
          setSearchQuery(query);
          refreshSearch(query);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") selectSearchMatch(searchIndex + (event.shiftKey ? -1 : 1));
          if (event.key === "Escape") closeSearch();
        }}
        placeholder="Find"
        aria-label="Find in document"
        className={cn(
          "w-24 min-w-0 bg-transparent px-2 text-xs text-foreground outline-none",
          compact ? "h-6 sm:w-36" : "h-7 @[38rem]/preview-toolbar:w-36",
        )}
      />
      <span className="px-1 text-[10px] whitespace-nowrap text-muted-foreground tabular-nums">
        {searchCount ? `${searchIndex + 1}/${searchCount}` : "0/0"}
      </span>
      <button
        type="button"
        onClick={() => selectSearchMatch(searchIndex - 1)}
        disabled={!searchCount}
        aria-label="Previous search result"
        className="p-1 text-muted-foreground disabled:opacity-30"
      >
        <ChevronLeftIcon className="size-3.25" />
      </button>
      <button
        type="button"
        onClick={() => selectSearchMatch(searchIndex + 1)}
        disabled={!searchCount}
        aria-label="Next search result"
        className="p-1 text-muted-foreground disabled:opacity-30"
      >
        <ChevronRightIcon className="size-3.25" />
      </button>
    </div>
  );

  const searchToggle = (title: string) => (
    <button
      type="button"
      onClick={() => (searchOpen ? closeSearch() : setSearchOpen(true))}
      aria-label={searchOpen ? "Close document search" : "Search document"}
      aria-pressed={searchOpen}
      title={title}
      className={cn(toolbarButtonClass, searchOpen && pressedClass)}
    >
      <SearchIcon />
    </button>
  );

  const versionControls = chatId && (
    <DocumentVersionControls path={relPath} revision={mtime} chatId={chatId} buttonClassName={toolbarButtonClass} onChange={versionChanged} />
  );

  return (
    <section
      ref={viewerRef}
      className={cn("flex h-full min-h-0 flex-col overflow-hidden bg-background outline-none", isPresentation && presentationView === "reading" && "bg-[#111111]")}
      aria-label={`${meta.label} document viewer`}
      data-testid="workspace-document-preview"
      data-presentation-view={isPresentation ? presentationView : undefined}
      tabIndex={0}
      onKeyDown={(event) => handleViewerKeyDown(event)}
    >
      {runtimeBanner}
      {/* Controls show by the toolbar's own width, not the window's: the
          viewer sits in a side panel of a wide window. */}
      {presentationView !== "reading" && kind !== "xlsx" && (
        <header className="@container/preview-toolbar flex h-9 shrink-0 items-center justify-between gap-1 border-b border-border/60 bg-background px-1.5">
          <div className="flex min-w-0 items-center gap-1 overflow-hidden">
            {hasNavigator && (
              <button
                type="button"
                onClick={() => {
                  // Choosing a layout yourself overrides the live build's.
                  liveLayoutRef.current.restoreNavigator = false;
                  setNavigatorOpen((open) => !open);
                }}
                aria-label={
                  navigatorVisible
                    ? `Hide ${isPresentation ? "slide thumbnails" : "navigator"}`
                    : `Show ${isPresentation ? "slide thumbnails" : "navigator"}`
                }
                aria-pressed={navigatorVisible}
                disabled={isPresentation && presentationView === "sorter"}
                title={navigatorVisible ? "Hide navigator" : "Show navigator"}
                className={cn(toolbarButtonClass, navigatorVisible && pressedClass)}
              >
                <PanelLeftIcon />
              </button>
            )}
            {searchToggle("Search")}
            {searchOpen && searchBox(false)}
            {!searchOpen && (
              <span className="hidden min-w-0 items-center gap-1.5 pl-1 @[48rem]/preview-toolbar:flex">
                <span className="size-2 shrink-0 rounded-[2px]" style={{ backgroundColor: meta.accent }} aria-hidden="true" />
                <span className="max-w-36 truncate text-[11px] font-medium text-foreground/80" title={name}>
                  {name}
                </span>
              </span>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={() => goToItem(activeIndex - 1)}
              disabled={activeIndex <= 0}
              aria-label={`Previous ${itemName.toLowerCase()}`}
              className={cn(toolbarButtonClass, "hidden @[32rem]/preview-toolbar:flex")}
            >
              <ChevronLeftIcon />
            </button>
            {/* A narrow toolbar keeps a compact "1/4" counter. */}
            <span className="text-center text-[10px] text-muted-foreground tabular-nums @[32rem]/preview-toolbar:min-w-20" role="status" title={status}>
              {itemCount > 0 && (
                <span className="px-1 @[32rem]/preview-toolbar:hidden">
                  {activeIndex + 1}/{itemCount}
                </span>
              )}
              <span className="hidden @[32rem]/preview-toolbar:inline">{status}</span>
            </span>
            <button
              type="button"
              onClick={() => goToItem(activeIndex + 1)}
              disabled={activeIndex >= itemCount - 1}
              aria-label={`Next ${itemName.toLowerCase()}`}
              className={cn(toolbarButtonClass, "hidden @[32rem]/preview-toolbar:flex")}
            >
              <ChevronRightIcon />
            </button>
          </div>

          <div className="flex shrink-0 items-center gap-0.5">
            {sessionDocument && chatId && (
              <div className="flex items-center gap-0.5 border-r border-border/60 pr-1.5">
                {isPresentation && (
                  <button
                    type="button"
                    onClick={() => setAnnotating((value) => !value)}
                    disabled={!canAnnotate}
                    aria-label={annotateActive ? "Stop selecting areas to edit" : "Select an area to edit"}
                    aria-pressed={annotateActive}
                    title={deckBeingBuilt ? "Available when the deck is finished" : "Select a shape or area and tell the agent what to change"}
                    className={cn(toolbarButtonClass, annotateActive && annotateClass)}
                  >
                    <SquareDashedMousePointerIcon aria-hidden="true" />
                  </button>
                )}
                {versionControls}
              </div>
            )}
            {isPresentation && (
              <div
                className="hidden items-center gap-0.5 @[23rem]/preview-toolbar:flex @[38rem]/preview-toolbar:pr-1.5"
                role="toolbar"
                aria-label="PowerPoint View controls"
              >
                <button
                  type="button"
                  onClick={() => setPresentationView("normal")}
                  aria-label="Normal view"
                  aria-pressed={presentationView === "normal"}
                  title="Normal view"
                  className={cn(toolbarButtonClass, presentationView === "normal" && pressedClass)}
                >
                  <PanelsTopLeftIcon aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => setPresentationView("sorter")}
                  aria-label="Slide sorter view"
                  aria-pressed={presentationView === "sorter"}
                  title="Slide sorter"
                  className={cn(toolbarButtonClass, presentationView === "sorter" && pressedClass)}
                >
                  <LayoutGridIcon aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={enterReadingView}
                  aria-label="Start Reading View slide show"
                  aria-pressed="false"
                  title="Reading view"
                  className={toolbarButtonClass}
                >
                  <MonitorPlayIcon aria-hidden="true" />
                </button>
                {hasSlideNotes && (
                  <button
                    type="button"
                    onClick={() => {
                      setPresentationView("normal");
                      setNotesOpen((open) => !open);
                    }}
                    aria-label={notesOpen ? "Hide speaker notes" : "Show speaker notes"}
                    aria-pressed={notesOpen}
                    title="Speaker notes"
                    className={cn(toolbarButtonClass, notesOpen && pressedClass)}
                  >
                    <NotepadTextIcon aria-hidden="true" />
                  </button>
                )}
              </div>
            )}
            <div className="hidden items-center gap-0.5 border-l border-border/60 pl-1.5 @[40rem]/preview-toolbar:flex">
              <button type="button" onClick={() => applyZoom(zoom - 10)} aria-label="Zoom out" title="Zoom out" className={toolbarButtonClass}>
                <ZoomOutIcon />
              </button>
              <span className="w-9 text-center text-[10px] text-muted-foreground tabular-nums" aria-label={`Zoom ${zoom} percent`}>
                {zoom}%
              </span>
              <button type="button" onClick={() => applyZoom(zoom + 10)} aria-label="Zoom in" title="Zoom in" className={toolbarButtonClass}>
                <ZoomInIcon />
              </button>
              <button
                type="button"
                onClick={() => fitDocument("width")}
                aria-label="Fit width"
                title="Fit width"
                className={cn(toolbarButtonClass, fitMode === "width" && pressedClass)}
              >
                <MoveHorizontalIcon />
              </button>
              <button
                type="button"
                onClick={() => fitDocument("page")}
                aria-label="Fit page"
                title="Fit page"
                className={cn(toolbarButtonClass, fitMode === "page" && pressedClass)}
              >
                <Maximize2Icon />
              </button>
            </div>
          </div>
        </header>
      )}

      {kind === "xlsx" && (
        <div className="flex h-8 shrink-0 items-center border-b border-border/60 bg-background text-[11px]">
          <div
            className="flex h-full w-16 shrink-0 items-center border-r border-border/60 px-2 font-mono font-medium text-foreground/80"
            aria-label="Selected cell"
          >
            {selectedCell?.name || "—"}
          </div>
          <div className="flex min-w-0 flex-1 items-center gap-2 px-2" aria-label="Formula bar">
            <span className="shrink-0 font-serif text-muted-foreground italic" aria-hidden="true">
              fx
            </span>
            <span className="truncate font-mono text-foreground/80">{selectedCell?.value || ""}</span>
          </div>
          {sessionDocument && chatId && (
            <div className="flex shrink-0 items-center gap-0.5 border-l border-border/60 px-0.5">
              <button
                type="button"
                onClick={() => setAnnotating((value) => !value)}
                disabled={!canAnnotate}
                aria-label={annotateActive ? "Stop selecting cells to edit" : "Select cells to edit"}
                aria-pressed={annotateActive}
                title={deckBeingBuilt ? "Available when the workbook is finished" : "Select a cell or range and tell the agent what to change"}
                className={cn(toolbarButtonClass, annotateActive && annotateClass)}
              >
                <SquareDashedMousePointerIcon aria-hidden="true" />
              </button>
              {exactRenderer && (
                <button
                  type="button"
                  onClick={() => {
                    setAnnotating(false);
                    setPrintLayout((value) => !value);
                  }}
                  aria-label="Print layout"
                  aria-pressed={printLayout}
                  title={printLayout ? "Back to the cell grid" : "Show the exact print layout"}
                  className={cn(toolbarButtonClass, printLayout && pressedClass)}
                >
                  <PrinterIcon aria-hidden="true" />
                </button>
              )}
              {versionControls}
            </div>
          )}
          <div className="flex shrink-0 items-center gap-0.5 border-l border-border/60 px-0.5">
            {searchToggle("Search workbook")}
            {searchOpen && searchBox(true)}
          </div>
        </div>
      )}

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {navigatorVisible && isPresentation && (
          <nav
            className="z-20 w-40 shrink-0 overflow-y-auto border-r border-border/60 bg-background p-1.5 max-[640px]:absolute max-[640px]:inset-y-0 max-[640px]:left-0 max-[640px]:shadow-xl"
            aria-label="Slide thumbnails"
          >
            <div className="space-y-1.5">
              {entries.map((entry) => {
                const selected = activeIndex === entry.index;
                return (
                  <button
                    key={`${entry.label}:${entry.index}`}
                    type="button"
                    onClick={() => {
                      goToItem(entry.index);
                      if (window.matchMedia?.("(max-width: 640px)").matches) setNavigatorOpen(false);
                    }}
                    aria-label={`Go to slide ${entry.index + 1}: ${entry.label}`}
                    aria-current={selected ? "page" : undefined}
                    className={cn(
                      "flex w-full items-start gap-1.5 rounded-sm p-1 text-left transition-colors hover:bg-accent",
                      selected && "bg-brand/8",
                    )}
                  >
                    <span
                      className={cn(
                        "w-4 shrink-0 pt-1 text-right text-[10px] text-muted-foreground tabular-nums",
                        selected && "font-semibold text-brand",
                      )}
                    >
                      {entry.index + 1}
                    </span>
                    <span
                      className="relative min-w-0 flex-1 overflow-hidden rounded-[2px] border-2 bg-white shadow-sm"
                      style={{
                        aspectRatio: slideAspectRatio,
                        borderColor: selected ? "var(--brand)" : "var(--border)",
                      }}
                    >
                      <SlideThumbnail html={slidePreviewMeta[entry.index]?.thumbnailHtml} label={`Thumbnail for slide ${entry.index + 1}`} />
                    </span>
                  </button>
                );
              })}
            </div>
          </nav>
        )}
        {navigatorVisible && !isPresentation && (
          <nav
            className="z-10 w-36 shrink-0 overflow-y-auto border-r border-border/60 bg-background p-1.5 max-[640px]:absolute max-[640px]:inset-y-0 max-[640px]:left-0 max-[640px]:shadow-xl"
            aria-label="Document navigator"
          >
            <div className="space-y-0.5">
              {entries.map((entry) => (
                <button
                  key={`${entry.label}:${entry.index}`}
                  type="button"
                  onClick={() => goToItem(entry.index)}
                  aria-current={activeIndex === entry.index ? "page" : undefined}
                  className={cn(
                    "flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[11px] transition-colors",
                    activeIndex === entry.index ? "bg-accent font-medium text-foreground" : "text-muted-foreground hover:bg-accent",
                  )}
                >
                  <span className={cn("w-4 shrink-0 text-right text-[10px] tabular-nums", activeIndex === entry.index && "text-brand")}>
                    {entry.index + 1}
                  </span>
                  <span className="truncate" title={entry.label}>
                    {entry.label}
                  </span>
                </button>
              ))}
            </div>
          </nav>
        )}
        <div className={cn("flex min-w-0 flex-1 flex-col", isPresentation && presentationView === "reading" ? "bg-[#111111]" : "bg-[#e8eaed]")}>
          <div className="relative min-h-0 flex-1">
            <iframe
              ref={iframeRef}
              title={`Preview ${name}`}
              srcDoc={currentResult.html}
              onLoad={handleFrameLoad}
              sandbox="allow-same-origin"
              referrerPolicy="no-referrer"
              className={cn(
                "h-full min-h-0 w-full border-0",
                isPresentation && presentationView === "reading" ? "bg-[#111111]" : "bg-[#e8eaed]",
              )}
              data-testid="document-preview-frame"
            />
            {canAnnotate && chatId && (
              <DeckAnnotator
                frameRef={iframeRef}
                frameKey={currentResult.html}
                chatId={chatId}
                file={relPath}
                active={annotateActive}
                agentWorking={agentWorking}
                onExit={() => setAnnotating(false)}
              />
            )}
            {isPresentation && presentationView === "sorter" && (
              <section className="absolute inset-0 overflow-y-auto bg-[#e5e5e5] p-4 sm:p-6" aria-label="Slide sorter">
                <div className="mx-auto grid max-w-6xl grid-cols-1 gap-x-5 gap-y-6 min-[460px]:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
                  {entries.map((entry) => {
                    const selected = activeIndex === entry.index;
                    return (
                      <button
                        key={`sorter:${entry.label}:${entry.index}`}
                        type="button"
                        onClick={() => {
                          goToItem(entry.index);
                          setPresentationView("normal");
                        }}
                        aria-label={`Open slide ${entry.index + 1}: ${entry.label}`}
                        aria-current={selected ? "page" : undefined}
                        className="group min-w-0 rounded-sm text-left outline-none"
                      >
                        <span
                          className="block overflow-hidden rounded-[3px] border-2 bg-white shadow-md transition group-hover:shadow-lg group-focus-visible:ring-2 group-focus-visible:ring-brand/50"
                          style={{ aspectRatio: slideAspectRatio, borderColor: selected ? "var(--brand)" : "transparent" }}
                        >
                          <SlideThumbnail html={slidePreviewMeta[entry.index]?.thumbnailHtml} label={`Sorter preview for slide ${entry.index + 1}`} />
                        </span>
                        <span className="mt-1.5 flex min-w-0 items-center gap-2 px-0.5">
                          <span className={cn("text-[10px] text-[#525252] tabular-nums", selected && "font-semibold text-brand")}>
                            {entry.index + 1}
                          </span>
                          <span className="truncate text-[10px] text-[#525252]" title={entry.label}>
                            {entry.label}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>
            )}
            {isPresentation && presentationView === "reading" && (
              <section className="pointer-events-none absolute inset-0 z-10" aria-label="PowerPoint reading view">
                <div className="absolute inset-x-0 top-0 flex items-start justify-between gap-3 bg-gradient-to-b from-black/75 to-transparent p-3 text-white sm:p-4">
                  <div className="min-w-0 rounded-full bg-black/55 px-3 py-1.5 shadow-lg backdrop-blur-sm">
                    <p className="truncate text-[11px] font-medium" title={name}>
                      {name}
                    </p>
                    <p className="text-[9px] text-white/65">Reading View · Slide Show</p>
                  </div>
                  <div className="pointer-events-auto flex shrink-0 items-center gap-1.5">
                    {fullscreenSupported && (
                      <button
                        type="button"
                        onClick={() => void toggleFullscreen()}
                        aria-label={isFullscreen ? "Exit full screen" : "Enter full screen"}
                        className={readingButtonClass}
                      >
                        {isFullscreen ? <Minimize2Icon className="size-4.5" aria-hidden="true" /> : <Maximize2Icon className="size-4.5" aria-hidden="true" />}
                      </button>
                    )}
                    <button type="button" onClick={exitReadingView} aria-label="Exit Reading View" className={readingButtonClass}>
                      <XIcon className="size-4.5" aria-hidden="true" />
                    </button>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => goToItem(activeIndex - 1)}
                  disabled={activeIndex <= 0}
                  aria-label="Previous slide in Reading View"
                  className="pointer-events-auto absolute top-1/2 left-2 flex h-12 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 text-white shadow-lg backdrop-blur-sm transition hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:pointer-events-none disabled:opacity-0 sm:left-4 sm:h-14 sm:w-12"
                >
                  <ChevronLeftIcon className="size-6" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => goToItem(activeIndex + 1)}
                  disabled={activeIndex >= itemCount - 1}
                  aria-label="Next slide in Reading View"
                  className="pointer-events-auto absolute top-1/2 right-2 flex h-12 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 text-white shadow-lg backdrop-blur-sm transition hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:pointer-events-none disabled:opacity-0 sm:right-4 sm:h-14 sm:w-12"
                >
                  <ChevronRightIcon className="size-6" aria-hidden="true" />
                </button>

                <div
                  className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-black/60 px-3 py-1.5 text-[11px] font-medium text-white tabular-nums shadow-lg backdrop-blur-sm sm:bottom-4"
                  role="status"
                  aria-live="polite"
                >
                  {status}
                </div>
              </section>
            )}
          </div>
          {kind === "xlsx" && itemCount > 0 && (
            <footer className="flex h-8 shrink-0 items-center border-t border-border/60 bg-background">
              <nav className="flex min-w-0 flex-1 items-end gap-0.5 self-stretch overflow-x-auto px-1.5" aria-label="Workbook sheets">
                {entries.map((entry) => (
                  <button
                    key={`sheet:${entry.label}:${entry.index}`}
                    type="button"
                    onClick={() => goToItem(entry.index)}
                    aria-label={`Open sheet ${entry.index + 1}: ${entry.label}`}
                    aria-current={activeIndex === entry.index ? "page" : undefined}
                    className={cn(
                      "relative flex h-8 max-w-40 shrink-0 items-center px-3 text-[10px] text-muted-foreground transition-colors hover:bg-accent",
                      activeIndex === entry.index &&
                        "bg-accent font-medium text-foreground after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full after:bg-brand",
                    )}
                    title={entry.label}
                  >
                    <span className="truncate">{entry.label}</span>
                  </button>
                ))}
              </nav>
              <div className="flex shrink-0 items-center gap-0.5 border-l border-border/60 px-1">
                <button type="button" onClick={() => applyZoom(zoom - 10)} aria-label="Zoom out" title="Zoom out" className={footerButtonClass}>
                  <ZoomOutIcon />
                </button>
                <span className="w-9 text-center text-[10px] text-muted-foreground tabular-nums" aria-label={`Zoom ${zoom} percent`}>
                  {zoom}%
                </span>
                <button type="button" onClick={() => applyZoom(zoom + 10)} aria-label="Zoom in" title="Zoom in" className={footerButtonClass}>
                  <ZoomInIcon />
                </button>
                <button
                  type="button"
                  onClick={() => fitDocument("width")}
                  aria-label="Fit width"
                  title="Fit width"
                  className={cn(footerButtonClass, fitMode === "width" && pressedClass)}
                >
                  <MoveHorizontalIcon />
                </button>
                <button
                  type="button"
                  onClick={() => fitDocument("page")}
                  aria-label="Fit page"
                  title="Fit page"
                  className={cn(footerButtonClass, "hidden sm:flex", fitMode === "page" && pressedClass)}
                >
                  <Maximize2Icon />
                </button>
              </div>
            </footer>
          )}
          {isPresentation && presentationView === "normal" && notesOpen && hasSlideNotes && (
            <section className="h-28 shrink-0 overflow-y-auto border-t border-border bg-background px-4 py-2 sm:h-32" aria-label="Speaker notes">
              <div className="mx-auto max-w-4xl">
                <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
                  <NotepadTextIcon className="size-3" aria-hidden="true" /> Notes
                </div>
                <p className="text-xs leading-5 whitespace-pre-wrap text-foreground/80">{activeSlideNotes || "No notes for this slide."}</p>
              </div>
            </section>
          )}
        </div>
      </div>
    </section>
  );
}
