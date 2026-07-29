import { useState } from "react"
import { Combobox as ComboboxPrimitive } from "@base-ui/react/combobox"
import { Check, ChevronDown, Search, X } from "lucide-react"

import { cn } from "@/lib/utils"

export interface ComboboxItem {
  value: string
  label: string
  description?: string
  meta?: string
  keywords?: string
}

/**
 * A searchable single-select — the native `<select>`/`NativeSelect` swapped
 * in wherever the option list is long enough that scrolling to find one
 * (a project's units, its modules, ...) is worse than typing to filter.
 * Small, fixed-length lists (a pipeline picker, a case-set toggle) should
 * stay `NativeSelect` — this isn't a blanket replacement.
 *
 * Wraps `@base-ui/react/combobox` (already a dependency, used by `Select`)
 * with the same trigger/popup token language as `select.tsx` so it reads
 * as the same control family, just with a search field instead of a
 * fixed-height listbox.
 */
export function Combobox({
  items,
  value,
  onValueChange,
  placeholder,
  emptyText = "No matches.",
  className,
  popupClassName,
  size = "default",
  disabled,
  ariaLabel,
  searchPlaceholder = "Search…",
}: {
  items: ComboboxItem[]
  value: string | null
  onValueChange: (value: string | null) => void
  placeholder?: string
  emptyText?: string
  className?: string
  popupClassName?: string
  size?: "sm" | "default"
  disabled?: boolean
  ariaLabel?: string
  searchPlaceholder?: string
}) {
  const selected = items.find((item) => item.value === value) ?? null
  const rich = items.some((item) => item.description || item.meta)
  const [query, setQuery] = useState("")

  return (
    <ComboboxPrimitive.Root<ComboboxItem>
      items={items}
      value={selected}
      inputValue={query}
      onInputValueChange={setQuery}
      onOpenChange={(open) => {
        if (!open) setQuery("")
      }}
      onValueChange={(item) => {
        onValueChange(item?.value ?? null)
        setQuery("")
      }}
      itemToStringLabel={(item) => item.label}
      filter={(item, query) => {
        const haystack = [item.label, item.value, item.description, item.meta, item.keywords]
          .filter(Boolean)
          .join(" ")
          .toLocaleLowerCase()
        return haystack.includes(query.trim().toLocaleLowerCase())
      }}
      isItemEqualToValue={(a, b) => a.value === b.value}
      disabled={disabled}
      autoHighlight
    >
      <div
        className={cn(
          "relative flex items-center rounded-md border border-(--color-border) bg-(--bg-page) transition-colors focus-within:border-(--focus-ring) focus-within:ring-2 focus-within:ring-(--focus-ring)/25 hover:border-(--color-border-strong)",
          size === "sm" ? "h-7" : "h-9",
          disabled && "cursor-not-allowed opacity-60",
          className,
        )}
      >
        <ComboboxPrimitive.Trigger
          aria-label={ariaLabel}
          className={cn(
            "flex h-full min-w-0 flex-1 items-center gap-2 bg-transparent pl-2.5 text-left outline-none",
            selected && !disabled ? "pr-14" : "pr-7",
          )}
        >
          <ComboboxPrimitive.Value placeholder={placeholder}>
            {selected ? (
              <span className="flex min-w-0 flex-1 items-center gap-2">
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate font-medium text-(--color-text)",
                    size === "sm" ? "text-xs" : "text-sm",
                  )}
                >
                  {selected.label}
                </span>
                {selected.meta && (
                  <span className="hidden shrink-0 font-mono text-[9px] text-(--color-text-subtle) sm:inline">
                    {selected.meta}
                  </span>
                )}
              </span>
            ) : (
              <span
                className={cn(
                  "truncate text-(--color-text-subtle)",
                  size === "sm" ? "text-xs" : "text-sm",
                )}
              >
                {placeholder}
              </span>
            )}
          </ComboboxPrimitive.Value>
        </ComboboxPrimitive.Trigger>
        {selected && !disabled && (
          <ComboboxPrimitive.Clear
            className="absolute right-7 flex h-5 w-5 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Clear selection"
          >
            <X size={12} />
          </ComboboxPrimitive.Clear>
        )}
        <ComboboxPrimitive.Icon className="pointer-events-none absolute right-2 flex items-center text-(--color-text-muted)">
          <ChevronDown size={14} />
        </ComboboxPrimitive.Icon>
      </div>

      <ComboboxPrimitive.Portal>
        <ComboboxPrimitive.Positioner side="bottom" align="start" sideOffset={4} className="z-(--z-modal)">
          <ComboboxPrimitive.Popup
            style={rich ? { width: "min(400px, calc(100vw - 16px))" } : undefined}
            className={cn(
              "flex max-h-72 w-(--anchor-width) min-w-40 flex-col overflow-hidden rounded-lg border border-(--color-border-strong) bg-(--bg-page) text-(--color-text) shadow-(--shadow-popover)",
              "data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
              popupClassName,
            )}
          >
            <ComboboxPrimitive.InputGroup className="m-1.5 flex h-8 shrink-0 items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 focus-within:border-(--focus-ring)">
              <Search size={12} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
              <ComboboxPrimitive.Input
                autoFocus
                aria-label={ariaLabel ? `Search ${ariaLabel}` : "Search options"}
                placeholder={searchPlaceholder}
                className="h-full min-w-0 flex-1 bg-transparent text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  className="flex h-5 w-5 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
                  aria-label="Clear search"
                >
                  <X size={11} />
                </button>
              )}
            </ComboboxPrimitive.InputGroup>
            <ComboboxPrimitive.Empty className="px-3 py-2 text-xs text-(--color-text-subtle)">
              {emptyText}
            </ComboboxPrimitive.Empty>
            <ComboboxPrimitive.List className="min-h-0 overflow-y-auto p-1.5 pt-0">
              {(item: ComboboxItem) => (
                <ComboboxPrimitive.Item
                  key={item.value}
                  value={item}
                  className={cn(
                    "relative flex w-full cursor-default items-center gap-2 rounded-sm pr-7 pl-2 text-sm text-(--color-text) outline-hidden select-none data-highlighted:bg-(--bg-key)",
                    rich ? "min-h-11 py-1.5" : "h-8 py-1",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="min-w-0 flex-1 truncate font-medium">{item.label}</span>
                      {item.meta && (
                        <span className="shrink-0 rounded bg-(--bg-subtle) px-1.5 py-0.5 font-mono text-[9px] text-(--color-text-subtle)">
                          {item.meta}
                        </span>
                      )}
                    </span>
                    {item.description && (
                      <span className="mt-0.5 block truncate text-[10px] leading-3.5 text-(--color-text-muted)">
                        {item.description}
                      </span>
                    )}
                  </span>
                  <ComboboxPrimitive.ItemIndicator className="absolute right-2 flex size-4 items-center justify-center text-(--color-accent)">
                    <Check size={13} />
                  </ComboboxPrimitive.ItemIndicator>
                </ComboboxPrimitive.Item>
              )}
            </ComboboxPrimitive.List>
          </ComboboxPrimitive.Popup>
        </ComboboxPrimitive.Positioner>
      </ComboboxPrimitive.Portal>
    </ComboboxPrimitive.Root>
  )
}
