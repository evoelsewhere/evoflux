import { Combobox as ComboboxPrimitive } from "@base-ui/react/combobox"
import { Check, ChevronDown, X } from "lucide-react"

import { cn } from "@/lib/utils"

export interface ComboboxItem {
  value: string
  label: string
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
  size = "default",
  disabled,
}: {
  items: ComboboxItem[]
  value: string | null
  onValueChange: (value: string | null) => void
  placeholder?: string
  emptyText?: string
  className?: string
  size?: "sm" | "default"
  disabled?: boolean
}) {
  const selected = items.find((item) => item.value === value) ?? null

  return (
    <ComboboxPrimitive.Root<ComboboxItem>
      items={items}
      value={selected}
      onValueChange={(item) => onValueChange(item?.value ?? null)}
      itemToStringLabel={(item) => item.label}
      isItemEqualToValue={(a, b) => a.value === b.value}
      disabled={disabled}
    >
      <ComboboxPrimitive.InputGroup
        data-slot="combobox-input-group"
        className={cn(
          "flex items-center gap-1 rounded-[10px] border border-(--color-border) bg-(--bg-page) pr-1.5 pl-2.5 transition-colors focus-within:border-(--focus-ring) focus-within:ring-2 focus-within:ring-(--focus-ring)/25 hover:border-(--color-border-strong)",
          "data-[size=sm]:h-7 data-[size=default]:h-9",
          disabled && "cursor-not-allowed opacity-60",
          className,
        )}
        data-size={size}
      >
        <ComboboxPrimitive.Input
          placeholder={placeholder}
          className="h-full w-full min-w-0 bg-transparent text-sm text-(--color-text) outline-none placeholder:text-(--color-text-subtle) data-[size=sm]:text-xs"
        />
        {selected && !disabled && (
          <ComboboxPrimitive.Clear
            className="flex shrink-0 items-center justify-center rounded p-0.5 text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Clear selection"
          >
            <X size={12} />
          </ComboboxPrimitive.Clear>
        )}
        <ComboboxPrimitive.Icon className="pointer-events-none flex shrink-0 items-center text-(--color-text-muted)">
          <ChevronDown size={14} />
        </ComboboxPrimitive.Icon>
      </ComboboxPrimitive.InputGroup>

      <ComboboxPrimitive.Portal>
        <ComboboxPrimitive.Positioner side="bottom" align="start" sideOffset={4} className="z-(--z-modal)">
          <ComboboxPrimitive.Popup
            className={cn(
              "max-h-64 w-(--anchor-width) min-w-40 overflow-y-auto rounded-[12px] border border-(--color-border-strong) bg-(--bg-page) p-1.5 text-(--color-text) shadow-(--shadow-popover)",
              "data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
            )}
          >
            <ComboboxPrimitive.Empty className="px-2.5 py-1.5 text-xs text-(--color-text-subtle)">
              {emptyText}
            </ComboboxPrimitive.Empty>
            <ComboboxPrimitive.List>
              {(item: ComboboxItem) => (
                <ComboboxPrimitive.Item
                  key={item.value}
                  value={item}
                  className="relative flex h-8 w-full cursor-default items-center gap-2 rounded-[8px] py-1 pr-7 pl-2.5 text-sm text-(--color-text) outline-hidden select-none data-highlighted:bg-(--bg-key)"
                >
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
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
