import { type ReactNode, type RefObject, useState } from "react"
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
 * A searchable single-select used wherever the option list is long enough
 * that scrolling to find one (a project's units, its modules, ...) is worse
 * than typing to filter. Small, fixed-length lists should use `SelectControl`.
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
  clearable = true,
  renderLeadingIcon,
  anchor,
  footer,
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
  clearable?: boolean
  renderLeadingIcon?: (item: ComboboxItem) => ReactNode
  /**
   * Element the popup positions against and takes its width from
   * (``--anchor-width``). Defaults to the trigger. Use it when the trigger
   * sits inside a larger row the popup should line up with.
   */
  anchor?: RefObject<Element | null>
  /** Actions pinned under the list, e.g. "Create …". ``close`` dismisses the popup. */
  footer?: (close: () => void) => ReactNode
}) {
  const selected = items.find((item) => item.value === value) ?? null
  const rich = items.some((item) => item.description || item.meta)
  const twoLine = items.some((item) => item.description)
  const [query, setQuery] = useState("")
  const [open, setOpen] = useState(false)
  const canClear = clearable && selected && !disabled
  const small = size === "sm"

  return (
    <ComboboxPrimitive.Root<ComboboxItem>
      items={items}
      value={selected}
      inputValue={query}
      onInputValueChange={setQuery}
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setQuery("")
      }}
      onValueChange={(item) => {
        onValueChange(item?.value ?? null)
        // Clearing the query counts as input and would otherwise keep the
        // popup open after a pick.
        setQuery("")
        setOpen(false)
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
            canClear ? "pr-14" : "pr-7",
          )}
        >
          <ComboboxPrimitive.Value placeholder={placeholder}>
            {selected ? (
              <span className="flex min-w-0 flex-1 items-center gap-2">
                {renderLeadingIcon?.(selected)}
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate font-medium text-(--color-text)",
                    size === "sm" ? "text-xs" : "text-sm",
                  )}
                >
                  {selected.label}
                </span>
                {/* `meta` is a hint for telling list rows apart; on the closed
                    trigger it only took width from the label. */}
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
        {canClear && (
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
        <ComboboxPrimitive.Positioner
          side="bottom"
          align="start"
          sideOffset={4}
          anchor={anchor}
          className="z-(--z-modal)"
        >
          <ComboboxPrimitive.Popup
            data-no-drag
            className={cn(
              "flex max-h-72 w-(--anchor-width) max-w-[calc(100vw-16px)] min-w-40 flex-col overflow-hidden rounded-lg border border-(--color-border-strong) bg-(--bg-page) text-(--color-text) shadow-(--shadow-popover)",
              "data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
              // Rich rows need room for their meta/description — unless the
              // caller anchors the popup to a row whose width it should match.
              rich && !anchor && "w-[min(320px,calc(100vw-16px))]",
              popupClassName,
            )}
          >
            <ComboboxPrimitive.InputGroup className="m-1 flex h-7 shrink-0 items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 focus-within:border-(--focus-ring)">
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
            {/* Base UI keeps this element mounted and only drops its text
                while there are matches; without ``empty:hidden`` its padding
                left a blank band between the search field and the list. */}
            <ComboboxPrimitive.Empty className="px-3 py-2 text-xs text-(--color-text-subtle) empty:hidden">
              {emptyText}
            </ComboboxPrimitive.Empty>
            <ComboboxPrimitive.List className="min-h-0 overflow-y-auto p-1 pt-0">
              {(item: ComboboxItem) => (
                <ComboboxPrimitive.Item
                  key={item.value}
                  value={item}
                  className={cn(
                    "relative flex w-full cursor-default items-center gap-2 rounded-md pr-7 pl-2 text-(--color-text) outline-hidden select-none data-highlighted:bg-(--bg-key) data-selected:bg-(--bg-key)/60",
                    small ? "text-xs" : "text-sm",
                    twoLine ? "min-h-10 py-1" : small ? "h-8" : "h-9",
                  )}
                >
                  {renderLeadingIcon?.(item)}
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="min-w-0 flex-1 truncate font-medium">{item.label}</span>
                      {item.meta && (
                        <span className="shrink-0 text-[10px] tabular-nums text-(--color-text-subtle)">
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
            {footer && (
              <div className="shrink-0 border-t border-(--color-border-subtle) p-1">
                {footer(() => setOpen(false))}
              </div>
            )}
          </ComboboxPrimitive.Popup>
        </ComboboxPrimitive.Positioner>
      </ComboboxPrimitive.Portal>
    </ComboboxPrimitive.Root>
  )
}
