import * as React from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { ArrowUpRightIcon, SearchIcon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogOverlay, DialogPortal, DialogTitle } from "@/components/ui/dialog";
import { REPOSITORY_URL, openLink } from "@/features/shell/app-commands";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import { matchesQuery, settingsGroups, settingsPages } from "./settings-registry";

const FOOTER_LINKS = [
  { label: "Documentation", url: `${REPOSITORY_URL}#readme` },
  { label: "Report an issue", url: `${REPOSITORY_URL}/issues/new` },
];

/**
 * Settings as a modal over the app: a title bar with the close button, the
 * section list on the left (search, groups split by a rule, links at the
 * bottom) and the open section scrolling on the right.
 */
export function SettingsDialog() {
  const open = useUiStore((s) => s.settingsOpen);
  const closeSettings = useUiStore((s) => s.closeSettings);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && closeSettings()}>
      <DialogPortal>
        <DialogOverlay className="bg-black/50 supports-backdrop-filter:backdrop-blur-[2px]" />
        <DialogPrimitive.Popup
          data-slot="settings-dialog"
          className={cn(
            "fixed top-1/2 left-1/2 z-50 flex h-[min(820px,calc(100%-4rem))] w-[min(1040px,calc(100%-3rem))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl bg-background text-foreground shadow-modal outline-none",
            "duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          )}
        >
          <header className="flex h-12 shrink-0 items-center justify-between border-b pr-2.5 pl-4">
            <DialogTitle className="text-[15px] font-semibold">Settings</DialogTitle>
            <DialogPrimitive.Close
              render={<Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-foreground" />}
            >
              <XIcon className="size-[18px]" />
              <span className="sr-only">Close</span>
            </DialogPrimitive.Close>
          </header>
          <div className="flex min-h-0 flex-1">
            <SettingsNav />
            <SettingsContent />
          </div>
        </DialogPrimitive.Popup>
      </DialogPortal>
    </Dialog>
  );
}

function SettingsNav() {
  const section = useUiStore((s) => s.settingsSection);
  const openSettings = useUiStore((s) => s.openSettings);
  const [query, setQuery] = React.useState("");
  const visible = settingsPages.filter((page) => matchesQuery(page, query));
  const groups = settingsGroups
    .map((group) => visible.filter((page) => page.group === group))
    .filter((pages) => pages.length > 0);

  return (
    <nav aria-label="Settings sections" className="flex w-56 shrink-0 flex-col border-r p-2.5">
      <label className="flex h-8 items-center gap-2 rounded-lg px-2.5 text-sm shadow-[0_0_0_1px_var(--input)] transition-shadow focus-within:shadow-[0_0_0_1px_var(--ring)]">
        <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && visible[0]) openSettings(visible[0].id);
            // The first Escape clears the search; the next one closes settings.
            if (event.key === "Escape" && query) {
              event.stopPropagation();
              setQuery("");
            }
          }}
          placeholder="Search"
          aria-label="Search settings"
          className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground focus-visible:shadow-none"
        />
        {query && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => setQuery("")}
            className="text-muted-foreground hover:text-foreground"
          >
            <XIcon className="size-3.5" />
          </button>
        )}
      </label>

      <div className="mt-2 min-h-0 flex-1 overflow-y-auto">
        {groups.map((pages, index) => (
          <React.Fragment key={pages[0].group}>
            {index > 0 && <div aria-hidden className="mx-2.5 my-2 h-px bg-border" />}
            <ul className="flex flex-col gap-0.5">
              {pages.map((page) => {
                const active = page.id === section;
                return (
                  <li key={page.id}>
                    <button
                      type="button"
                      aria-current={active ? "page" : undefined}
                      onClick={() => openSettings(page.id)}
                      className={cn(
                        "flex h-8 w-full items-center gap-3 rounded-lg px-2.5 text-left text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                        active ? "bg-accent font-medium text-foreground" : "text-foreground/85 hover:bg-accent/60 hover:text-foreground",
                      )}
                    >
                      <page.icon className={cn("size-[18px] shrink-0", active ? "text-brand" : "text-muted-foreground")} />
                      <span className="truncate">{page.title}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </React.Fragment>
        ))}
        {visible.length === 0 && <p className="px-2.5 py-2 text-xs text-muted-foreground">No settings match “{query}”.</p>}
      </div>

      <ul className="flex flex-col gap-0.5 pt-2">
        {FOOTER_LINKS.map((link) => (
          <li key={link.label}>
            <button
              type="button"
              onClick={() => openLink(link.url)}
              className="flex h-7 w-full items-center justify-between rounded-md px-2.5 text-[13px] text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              {link.label}
              <ArrowUpRightIcon className="size-4" />
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function SettingsContent() {
  const section = useUiStore((s) => s.settingsSection);
  const page = settingsPages.find((p) => p.id === section) ?? settingsPages[0];
  const Section = page.component;
  const scroller = React.useRef<HTMLDivElement>(null);

  // Each section opens at its top.
  React.useEffect(() => {
    // Braces matter: newer engines return a promise from scrollTo.
    void scroller.current?.scrollTo({ top: 0 });
  }, [section]);

  return (
    <div ref={scroller} className="min-h-0 min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-6 pt-6 pb-12">
        <Section />
      </div>
    </div>
  );
}
