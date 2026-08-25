import * as React from "react"
import { Select as SelectPrimitive } from "@base-ui/react/select"
import { CheckIcon, ChevronDownIcon, ChevronUpIcon } from "lucide-react"

import { cn } from "@/lib/utils"

const Select = SelectPrimitive.Root

const EMPTY_SELECT_VALUE = "__evoflux_empty_select_value__"

interface SelectControlOption {
  value: string
  label: React.ReactNode
  disabled?: boolean
}

interface SelectControlProps {
  value: string | null
  onValueChange: (value: string) => void
  options: SelectControlOption[]
  placeholder?: React.ReactNode
  ariaLabel?: string
  disabled?: boolean
  size?: "sm" | "default"
  className?: string
  contentClassName?: string
  itemClassName?: string
  id?: string
}

function SelectValue({ className, ...props }: SelectPrimitive.Value.Props) {
  return (
    <SelectPrimitive.Value
      data-slot="select-value"
      className={cn("flex flex-1 text-left", className)}
      {...props}
    />
  )
}

function SelectTrigger({
  className,
  size = "default",
  children,
  ...props
}: SelectPrimitive.Trigger.Props & {
  size?: "sm" | "default"
}) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      data-size={size}
      className={cn(
        "flex w-fit items-center justify-between gap-1.5 rounded-md border border-(--color-border) bg-(--bg-page) py-1.5 pr-2 pl-2.5 text-sm text-(--color-text) whitespace-nowrap transition-colors outline-none select-none hover:border-(--color-border-strong) focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25 disabled:cursor-not-allowed disabled:bg-(--bg-key) disabled:opacity-60 aria-invalid:border-(--color-error) aria-invalid:ring-2 aria-invalid:ring-(--color-error)/20 data-placeholder:text-(--color-text-subtle) data-[size=default]:h-9 md:data-[size=default]:h-8 data-[size=sm]:h-8 md:data-[size=sm]:h-7 data-[size=sm]:rounded-sm *:data-[slot=select-value]:line-clamp-1 *:data-[slot=select-value]:flex *:data-[slot=select-value]:items-center *:data-[slot=select-value]:gap-1.5 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon
        render={
          <ChevronDownIcon className="pointer-events-none size-4 text-(--color-text-muted)" />
        }
      />
    </SelectPrimitive.Trigger>
  )
}

function SelectContent({
  className,
  children,
  side = "bottom",
  sideOffset = 4,
  align = "start",
  alignOffset = 0,
  alignItemWithTrigger = false,
  ...props
}: SelectPrimitive.Popup.Props &
  Pick<
    SelectPrimitive.Positioner.Props,
    "align" | "alignOffset" | "side" | "sideOffset" | "alignItemWithTrigger"
  >) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Positioner
        side={side}
        sideOffset={sideOffset}
        align={align}
        alignOffset={alignOffset}
        alignItemWithTrigger={alignItemWithTrigger}
        className="isolate z-(--z-modal)"
      >
        <SelectPrimitive.Popup
          data-slot="select-content"
          data-align-trigger={alignItemWithTrigger}
          className={cn(
            "relative isolate z-(--z-modal) max-h-(--available-height) w-(--anchor-width) max-w-[calc(100vw-1rem)] min-w-36 origin-(--transform-origin) overflow-x-hidden overflow-y-auto rounded-lg border border-(--color-border-strong) bg-(--bg-page) p-1 text-(--color-text) shadow-(--shadow-popover) duration-(--motion-instant) data-[align-trigger=true]:animate-none data-[side=bottom]:slide-in-from-top-2 data-[side=inline-end]:slide-in-from-left-2 data-[side=inline-start]:slide-in-from-right-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
            className
          )}
          {...props}
        >
          <SelectScrollUpButton />
          <SelectPrimitive.List>{children}</SelectPrimitive.List>
          <SelectScrollDownButton />
        </SelectPrimitive.Popup>
      </SelectPrimitive.Positioner>
    </SelectPrimitive.Portal>
  )
}

function SelectItem({
  className,
  children,
  ...props
}: SelectPrimitive.Item.Props) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(
        "relative flex h-8 w-full cursor-default items-center gap-2 rounded-sm py-1 pr-8 pl-2 text-sm text-(--color-text) outline-hidden select-none focus:bg-(--bg-key) data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 *:[span]:last:flex *:[span]:last:items-center *:[span]:last:gap-2",
        className
      )}
      {...props}
    >
      <SelectPrimitive.ItemText className="flex flex-1 shrink-0 gap-2 whitespace-nowrap">
        {children}
      </SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator
        render={
          <span className="pointer-events-none absolute right-2 flex size-4 items-center justify-center" />
        }
      >
        <CheckIcon className="pointer-events-none text-(--accent-blue)" />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  )
}

function SelectScrollUpButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollUpArrow>) {
  return (
    <SelectPrimitive.ScrollUpArrow
      data-slot="select-scroll-up-button"
      className={cn(
        "top-0 z-(--z-panel) flex w-full cursor-default items-center justify-center bg-(--bg-page) py-1 text-(--color-text-muted) [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      <ChevronUpIcon />
    </SelectPrimitive.ScrollUpArrow>
  )
}

function SelectScrollDownButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollDownArrow>) {
  return (
    <SelectPrimitive.ScrollDownArrow
      data-slot="select-scroll-down-button"
      className={cn(
        "bottom-0 z-(--z-panel) flex w-full cursor-default items-center justify-center bg-(--bg-page) py-1 text-(--color-text-muted) [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      <ChevronDownIcon />
    </SelectPrimitive.ScrollDownArrow>
  )
}

/**
 * Shared single-select for the common controlled-value case.
 *
 * Feature code should use this instead of a native `<select>` so trigger,
 * popup, focus, keyboard and theme behavior stay consistent across Tauri and
 * browser development. Use `Combobox` for long/searchable dynamic lists and
 * the lower-level exports below only for custom item layouts.
 */
function SelectControl({
  value,
  onValueChange,
  options,
  placeholder = "Select…",
  ariaLabel,
  disabled,
  size = "default",
  className,
  contentClassName,
  itemClassName,
  id,
}: SelectControlProps) {
  const internalValue = value === "" ? EMPTY_SELECT_VALUE : value
  const selected = options.find((option) => option.value === value)

  return (
    <Select
      value={internalValue}
      onValueChange={(nextValue) => {
        if (nextValue == null) return
        onValueChange(
          nextValue === EMPTY_SELECT_VALUE ? "" : String(nextValue),
        )
      }}
      disabled={disabled}
    >
      <SelectTrigger
        id={id}
        aria-label={ariaLabel}
        size={size}
        className={cn("w-full", className)}
      >
        <SelectValue>{selected?.label ?? placeholder}</SelectValue>
      </SelectTrigger>
      <SelectContent className={contentClassName}>
        {options.map((option) => (
          <SelectItem
            key={option.value || EMPTY_SELECT_VALUE}
            value={option.value || EMPTY_SELECT_VALUE}
            disabled={option.disabled}
            className={itemClassName}
          >
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export {
  Select,
  SelectControl,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
}
