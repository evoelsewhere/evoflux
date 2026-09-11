/**
 * Context-menu primitives — right-click (and touch long-press) menus.
 *
 * Thin wrappers over Base UI's ContextMenu, styled to match
 * ``dropdown-menu.tsx``. Base UI owns the parts that a hand-rolled
 * fixed-position menu always gets wrong: viewport flipping, Escape and
 * outside-press dismissal, focus restoration, roving keyboard navigation,
 * and submenu hover/keyboard timing.
 */
import type * as React from "react"
import { ContextMenu as ContextMenuPrimitive } from "@base-ui/react/context-menu"
import { Menu as MenuPrimitive } from "@base-ui/react/menu"
import { ChevronRightIcon } from "lucide-react"

import { cn } from "@/lib/utils"

const POPUP_CLASS =
  "z-(--z-modal) max-h-(--available-height) min-w-44 origin-(--transform-origin) overflow-x-hidden overflow-y-auto rounded-lg border border-(--color-border) bg-(--bg-card) p-1 text-(--color-text) shadow-xl duration-(--motion-instant) outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95"

const ITEM_CLASS =
  "group/context-menu-item relative flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-hidden select-none focus:bg-(--bg-key) focus:text-(--color-text) data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5"

function ContextMenu({ ...props }: ContextMenuPrimitive.Root.Props) {
  return <ContextMenuPrimitive.Root {...props} />
}

function ContextMenuTrigger({ className, ...props }: ContextMenuPrimitive.Trigger.Props) {
  return (
    <ContextMenuPrimitive.Trigger
      data-slot="context-menu-trigger"
      className={cn("outline-none", className)}
      {...props}
    />
  )
}

function ContextMenuContent({
  className,
  ...props
}: MenuPrimitive.Popup.Props) {
  return (
    <ContextMenuPrimitive.Portal>
      <ContextMenuPrimitive.Positioner className="isolate z-(--z-modal) outline-none">
        <ContextMenuPrimitive.Popup
          data-slot="context-menu-content"
          className={cn(POPUP_CLASS, className)}
          {...props}
        />
      </ContextMenuPrimitive.Positioner>
    </ContextMenuPrimitive.Portal>
  )
}

function ContextMenuItem({
  className,
  variant = "default",
  ...props
}: MenuPrimitive.Item.Props & { variant?: "default" | "destructive" }) {
  return (
    <ContextMenuPrimitive.Item
      data-slot="context-menu-item"
      data-variant={variant}
      className={cn(
        ITEM_CLASS,
        "data-[variant=destructive]:text-(--color-error) data-[variant=destructive]:focus:bg-(--color-error)/10 data-[variant=destructive]:*:[svg]:text-(--color-error)",
        className,
      )}
      {...props}
    />
  )
}

/**
 * Section heading inside a menu.
 *
 * A plain element, not Base UI's GroupLabel: that part requires a
 * surrounding `<Menu.Group>` and throws at render time without one, which is
 * a poor trade for a one-line caption.
 */
function ContextMenuLabel({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="context-menu-label"
      className={cn("px-2 py-1 text-xs font-medium text-(--color-text-muted)", className)}
      {...props}
    />
  )
}

function ContextMenuSeparator({ className }: { className?: string }) {
  return (
    <div
      role="separator"
      data-slot="context-menu-separator"
      className={cn("-mx-1 my-1 h-px bg-(--color-border)", className)}
    />
  )
}

function ContextMenuSub({ ...props }: MenuPrimitive.SubmenuRoot.Props) {
  return <ContextMenuPrimitive.SubmenuRoot {...props} />
}

function ContextMenuSubTrigger({
  className,
  children,
  ...props
}: MenuPrimitive.SubmenuTrigger.Props) {
  return (
    <ContextMenuPrimitive.SubmenuTrigger
      data-slot="context-menu-sub-trigger"
      className={cn(
        ITEM_CLASS,
        "data-popup-open:bg-(--bg-key) data-popup-open:text-(--color-text)",
        className,
      )}
      {...props}
    >
      {children}
      <ChevronRightIcon className="ml-auto" />
    </ContextMenuPrimitive.SubmenuTrigger>
  )
}

function ContextMenuSubContent({ className, ...props }: MenuPrimitive.Popup.Props) {
  return (
    <ContextMenuPrimitive.Portal>
      <ContextMenuPrimitive.Positioner
        className="isolate z-(--z-modal) outline-none"
        align="start"
        alignOffset={-4}
        side="inline-end"
        sideOffset={2}
      >
        <ContextMenuPrimitive.Popup
          data-slot="context-menu-sub-content"
          className={cn(POPUP_CLASS, "min-w-40", className)}
          {...props}
        />
      </ContextMenuPrimitive.Positioner>
    </ContextMenuPrimitive.Portal>
  )
}

export {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubTrigger,
  ContextMenuSubContent,
}
