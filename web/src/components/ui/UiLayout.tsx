import { Fragment, type ReactNode } from 'react'
import type { UiBlockNode, UiLayoutBlock } from './ui-block-types'

interface UiLayoutProps {
  block: UiLayoutBlock
  /**
   * Renders one section child at the given nesting depth. Supplied by
   * `UiBlockRenderer` (spec §2.2) so this component never imports the
   * renderer — keeps the recursion cycle-free.
   */
  renderChild: (child: UiBlockNode, depth: number) => ReactNode
  /** Nesting depth of this layout (root = 0); passed back into renderChild. */
  depth: number
}

/** Fixed class strings — no dynamic Tailwind class construction. */
const GRID_CLASS =
  'grid grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))] gap-3'
const STACK_CLASS = 'flex flex-col gap-3'

export function UiLayout({ block, renderChild, depth }: UiLayoutProps) {
  const isColumns = block.orientation === 'columns'
  return (
    <div className={isColumns ? GRID_CLASS : STACK_CLASS}>
      {block.sections.map((section, i) => (
        <section key={i} className="min-w-0">
          {section.title && (
            <p className="mb-1.5 text-xs font-medium text-(--color-text-muted)">
              {section.title}
            </p>
          )}
          <div className="flex min-w-0 flex-col gap-2">
            {section.children.map((child, j) => (
              <Fragment key={j}>{renderChild(child, depth + 1)}</Fragment>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
