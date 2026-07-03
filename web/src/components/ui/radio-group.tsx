import { Radio as RadioPrimitive } from "@base-ui/react/radio"
import { RadioGroup as RadioGroupPrimitive } from "@base-ui/react/radio-group"

import { cn } from "@/lib/utils"

function RadioGroup({ className, ...props }: RadioGroupPrimitive.Props) {
  return (
    <RadioGroupPrimitive
      data-slot="radio-group"
      className={cn("grid gap-2", className)}
      {...props}
    />
  )
}

function RadioGroupItem({ className, ...props }: RadioPrimitive.Root.Props) {
  return (
    <RadioPrimitive.Root
      data-slot="radio-group-item"
      className={cn(
        "flex size-[18px] shrink-0 items-center justify-center rounded-full border border-(--color-border-strong) bg-(--bg-page) transition-colors outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25 disabled:cursor-not-allowed disabled:opacity-50 data-checked:border-(--accent-blue) aria-invalid:border-(--color-error) aria-invalid:ring-2 aria-invalid:ring-(--color-error)/20",
        className
      )}
      {...props}
    >
      <RadioPrimitive.Indicator
        keepMounted
        className="size-2 rounded-full bg-(--accent-blue) opacity-0 transition-opacity data-checked:opacity-100"
      />
    </RadioPrimitive.Root>
  )
}

export { RadioGroup, RadioGroupItem }
