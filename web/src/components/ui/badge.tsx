import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-4xl border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow] duration-(--motion-fast) focus-visible:border-(--focus-ring) focus-visible:ring-[3px] focus-visible:ring-(--focus-ring)/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-(--color-error) aria-invalid:ring-(--color-error)/20 dark:aria-invalid:ring-(--color-error)/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-(--color-accent) text-(--color-text-on-accent) [a]:hover:bg-(--color-accent)/80",
        secondary:
          "bg-(--bg-key) text-(--color-text) [a]:hover:bg-(--bg-key)/80",
        destructive:
          "bg-(--color-error)/10 text-(--color-error) focus-visible:ring-(--color-error)/20 dark:bg-(--color-error)/20 dark:focus-visible:ring-(--color-error)/40 [a]:hover:bg-(--color-error)/20",
        outline:
          "border-(--color-border) text-(--color-text) [a]:hover:bg-(--bg-key) [a]:hover:text-(--color-text-muted)",
        ghost:
          "hover:bg-(--bg-key) hover:text-(--color-text-muted) dark:hover:bg-(--bg-key)/50",
        link: "text-(--color-accent) underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

// eslint-disable-next-line react-refresh/only-export-components
export { Badge, badgeVariants }
