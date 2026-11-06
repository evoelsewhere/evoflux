"use client"

import { Switch as SwitchPrimitive } from "@base-ui/react/switch"
import { cn } from "@/lib/utils"

/** An on/off toggle; the track takes the accent colour when on. */
function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "peer inline-flex h-5 w-9 shrink-0 cursor-default items-center rounded-full p-0.5 shadow-hairline transition-colors outline-none data-checked:bg-brand data-checked:shadow-none data-unchecked:bg-input data-disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-ring/50",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="pointer-events-none block size-4 rounded-full bg-background shadow-sm ring-1 ring-foreground/5 transition-transform duration-150 ease-swift data-checked:translate-x-4 data-checked:bg-white data-unchecked:translate-x-0 motion-reduce:transition-none"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
