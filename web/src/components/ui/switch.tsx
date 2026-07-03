import { Switch as SwitchPrimitive } from "@base-ui/react/switch"

import { cn } from "@/lib/utils"

function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-(--color-border-strong) bg-(--bg-key) p-0.5 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25 disabled:cursor-not-allowed disabled:opacity-50 data-checked:border-(--accent-blue) data-checked:bg-(--accent-blue)",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="size-3.5 rounded-full border border-(--color-border) bg-(--bg-card) transition-transform data-checked:translate-x-4 data-checked:border-(--color-text-on-accent) data-checked:bg-(--color-text-on-accent)" />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
