import { NumberField as NumberFieldPrimitive } from "@base-ui/react/number-field"
import { ChevronDownIcon, ChevronUpIcon } from "lucide-react"

import { cn } from "@/lib/utils"

function NumberInput({ className, ...props }: NumberFieldPrimitive.Root.Props) {
  return (
    <NumberFieldPrimitive.Root
      data-slot="number-input"
      className={cn("w-full", className)}
      {...props}
    />
  )
}

function NumberInputGroup({ className, ...props }: NumberFieldPrimitive.Group.Props) {
  return (
    <NumberFieldPrimitive.Group
      data-slot="number-input-group"
      className={cn(
        "flex h-9 w-full overflow-hidden rounded-[10px] border border-(--color-border) bg-(--bg-page) text-sm text-(--color-text) transition-colors focus-within:border-(--focus-ring) focus-within:ring-2 focus-within:ring-(--focus-ring)/25",
        className
      )}
      {...props}
    />
  )
}

function NumberInputField({ className, ...props }: NumberFieldPrimitive.Input.Props) {
  return (
    <NumberFieldPrimitive.Input
      data-slot="number-input-field"
      className={cn(
        "min-w-0 flex-1 bg-transparent px-3 font-mono text-sm tabular-nums outline-none placeholder:text-(--color-text-subtle) disabled:cursor-not-allowed disabled:opacity-60",
        className
      )}
      {...props}
    />
  )
}

function NumberInputStepper({ className }: { className?: string }) {
  return (
    <div
      data-slot="number-input-stepper"
      className={cn("flex w-8 shrink-0 flex-col border-l border-(--color-border)", className)}
    >
      <NumberFieldPrimitive.Increment className="flex flex-1 items-center justify-center text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-40">
        <ChevronUpIcon className="size-3" aria-hidden="true" />
      </NumberFieldPrimitive.Increment>
      <div className="h-px bg-(--color-border)" />
      <NumberFieldPrimitive.Decrement className="flex flex-1 items-center justify-center text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-40">
        <ChevronDownIcon className="size-3" aria-hidden="true" />
      </NumberFieldPrimitive.Decrement>
    </div>
  )
}

export { NumberInput, NumberInputField, NumberInputGroup, NumberInputStepper }
