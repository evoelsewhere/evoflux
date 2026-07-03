import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox"
import { CheckIcon, MinusIcon } from "lucide-react"

import { cn } from "@/lib/utils"

function Checkbox({ className, ...props }: CheckboxPrimitive.Root.Props) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        "peer flex size-[18px] shrink-0 items-center justify-center rounded-[4px] border border-(--color-border-strong) bg-(--bg-page) text-(--color-text-on-accent) transition-colors outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25 disabled:cursor-not-allowed disabled:opacity-50 data-checked:border-(--accent-blue) data-checked:bg-(--accent-blue) data-indeterminate:border-(--accent-blue) data-indeterminate:bg-(--accent-blue) aria-invalid:border-(--color-error) aria-invalid:ring-2 aria-invalid:ring-(--color-error)/20",
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator keepMounted>
        <CheckIcon className="hidden size-3 data-checked:block" aria-hidden="true" />
        <MinusIcon className="hidden size-3 data-indeterminate:block" aria-hidden="true" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}

export { Checkbox }
