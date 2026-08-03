import * as React from "react"

import { cn } from "@/lib/utils"
import { ChevronDownIcon } from "lucide-react"

type NativeSelectProps = Omit<React.ComponentProps<"select">, "size"> & {
  platformNative?: boolean
  size?: "sm" | "default"
}

function NativeSelect({
  className,
  platformNative = false,
  size = "default",
  ...props
}: NativeSelectProps) {
  return (
    <div
      className={cn(
        "group/native-select relative w-fit has-[select:disabled]:opacity-50",
        className
      )}
      data-slot="native-select-wrapper"
      data-size={size}
      data-platform-native={platformNative || undefined}
    >
      <select
        data-slot="native-select"
        data-size={size}
        data-platform-native={platformNative || undefined}
        className={cn(
          platformNative
            ? "w-full min-w-0 [color-scheme:light_dark] disabled:cursor-not-allowed"
            : "h-8 w-full min-w-0 appearance-none rounded-md border border-(--color-border) bg-transparent py-1 pr-8 pl-2.5 text-sm transition-colors outline-none select-none selection:bg-(--color-accent) selection:text-(--color-text-on-accent) placeholder:text-(--color-text-muted) focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40 disabled:pointer-events-none disabled:cursor-not-allowed aria-invalid:border-(--color-error) aria-invalid:ring-2 aria-invalid:ring-(--color-error)/20 data-[size=sm]:h-7 data-[size=sm]:rounded-[min(var(--radius-md),10px)] data-[size=sm]:py-0.5 dark:bg-(--bg-input)/30 dark:hover:bg-(--bg-input)/50 dark:aria-invalid:border-(--color-error)/50 dark:aria-invalid:ring-(--color-error)/40",
        )}
        {...props}
      />
      {!platformNative && (
        <ChevronDownIcon className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-(--color-text-muted) select-none" aria-hidden="true" data-slot="native-select-icon" />
      )}
    </div>
  )
}

function NativeSelectOption({
  className,
  ...props
}: React.ComponentProps<"option">) {
  return (
    <option
      data-slot="native-select-option"
      className={cn("bg-[Canvas] text-[CanvasText]", className)}
      {...props}
    />
  )
}

function NativeSelectOptGroup({
  className,
  ...props
}: React.ComponentProps<"optgroup">) {
  return (
    <optgroup
      data-slot="native-select-optgroup"
      className={cn("bg-[Canvas] text-[CanvasText]", className)}
      {...props}
    />
  )
}

export { NativeSelect, NativeSelectOptGroup, NativeSelectOption }
