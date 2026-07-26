import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Maximize2, Minimize2, Plus, X } from 'lucide-react'
import { useResizableWidth } from '@/hooks/use-resizable-width'
import { panelTransition, staggerDelay, useMotionPreset } from '@/lib/motion'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { cn } from '@/lib/utils'
import { type WorkbenchTool, useUIStore } from '@/stores/useUIStore'
import {
  isWorkbenchToolEnabled,
  WORKBENCH_TOOL_ORDER,
  WORKBENCH_TOOLS,
  type WorkbenchContext,
} from './tools'

interface WorkbenchDockProps extends WorkbenchContext {
  children: ReactNode
  className?: string
}

/**
 * The single resizable surface used by every auxiliary tool. Tool views stay
 * mounted inside it and are switched by the workbench tab model, preserving
 * terminals, browser sessions, tree expansion, and draft state.
 */
export function WorkbenchDock({
  children,
  className,
  mode,
  sessionId,
  workspace,
}: WorkbenchDockProps) {
  const open = useUIStore((state) => state.workbenchOpen)
  const tabs = useUIStore((state) => state.workbenchTabs)
  const activeTool = useUIStore((state) => state.activeWorkbenchTool)
  const maximized = useUIStore((state) => state.workbenchMaximized)
  const selectTool = useUIStore((state) => state.selectWorkbenchTool)
  const closeTool = useUIStore((state) => state.closeWorkbenchTool)
  const closeWorkbench = useUIStore((state) => state.closeWorkbench)
  const showLauncher = useUIStore((state) => state.showWorkbenchLauncher)
  const toggleMaximized = useUIStore((state) => state.toggleWorkbenchMaximized)
  const motionPreset = useMotionPreset()
  const resizable = useResizableWidth({
    storageKey: STORAGE_KEYS.panels.workbench,
    defaultWidth: 540,
    minWidth: 360,
    maxWidth: 1080,
    edge: 'left',
    disabled: maximized,
  })

  return (
    <AnimatePresence initial={false}>
      {open && (
    <motion.aside
      key="workbench-dock"
      layout="size"
      initial={{
        width: 0,
        opacity: 0,
        x: 18 * motionPreset.distance,
      }}
      animate={{
        width: maximized ? '100%' : resizable.width,
        opacity: 1,
        x: 0,
      }}
      exit={{
        width: 0,
        opacity: 0,
        x: 12 * motionPreset.distance,
      }}
      transition={resizable.isResizing ? { duration: 0 } : panelTransition(motionPreset)}
      className={cn(
        'relative flex h-full min-h-0 min-w-0 shrink-0 flex-col overflow-hidden border-l border-(--color-border) bg-(--bg-page) will-change-[width,transform,opacity]',
        maximized && 'flex-1',
        className,
      )}
      aria-label="Workbench tools"
    >
      {!maximized && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize workbench"
          title="Drag to resize · double-click to reset"
          onPointerDown={resizable.startResize}
          onDoubleClick={resizable.resetWidth}
          className="absolute -left-1 top-0 z-(--z-panel) h-full w-2 cursor-col-resize transition-colors hover:bg-(--color-accent)/35"
        />
      )}
      <motion.header
        layout="position"
        className="flex h-11 shrink-0 items-center gap-1 px-2"
      >
        <motion.div layout className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
          <AnimatePresence initial={false} mode="popLayout">
          {tabs.map((tab) => {
            const meta = WORKBENCH_TOOLS[tab.tool]
            const Icon = meta.icon
            const active = activeTool === tab.tool
            return (
              <motion.div
                layout
                key={tab.id}
                initial={{ opacity: 0, scale: 0.92, x: 8 * motionPreset.distance }}
                animate={{ opacity: 1, scale: 1, x: 0 }}
                exit={{ opacity: 0, scale: 0.9, x: -8 * motionPreset.distance }}
                transition={motionPreset.spring}
                className={cn(
                  'group relative flex h-8 min-w-11 max-w-44 flex-[0_1_11rem] items-center overflow-hidden rounded-lg border transition-colors',
                  active
                    ? 'border-(--color-border) text-(--color-text)'
                    : 'border-transparent text-(--color-text-muted) hover:bg-(--bg-key)/70 hover:text-(--color-text)',
                )}
              >
                {active && (
                  <motion.span
                    layoutId="workbench-active-tab"
                    className="absolute inset-0 rounded-lg bg-(--bg-key)"
                    transition={motionPreset.spring}
                  />
                )}
                <button
                  type="button"
                  onClick={() => selectTool(tab.tool)}
                  className="relative z-10 flex h-full min-w-0 flex-1 items-center gap-1.5 pl-2 pr-1"
                >
                  <Icon size={14} className="shrink-0" />
                  <span className="truncate text-xs font-medium">{meta.label}</span>
                </button>
                <button
                  type="button"
                  onClick={() => closeTool(tab.tool)}
                  className="mr-1 flex h-5 w-5 shrink-0 items-center justify-center rounded text-(--color-text-muted) opacity-0 hover:bg-(--bg-hover) hover:text-(--color-text) group-hover:opacity-100 focus:opacity-100"
                  aria-label={`Close ${meta.label}`}
                >
                  <X size={12} />
                </button>
              </motion.div>
            )
          })}
          </AnimatePresence>
          <motion.button
            layout
            type="button"
            onClick={showLauncher}
            whileHover={{ scale: 1.06 }}
            whileTap={{ scale: 0.92 }}
            transition={motionPreset.spring}
            className={cn(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors',
              activeTool === null
                ? 'bg-(--bg-key) text-(--color-text)'
                : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
            )}
            aria-label="Choose side panel tool"
            title="Choose side panel tool"
          >
            <Plus size={16} />
          </motion.button>
        </motion.div>

        {activeTool && (
          <motion.button
            layout
            type="button"
            onClick={toggleMaximized}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.92 }}
            transition={motionPreset.spring}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label={maximized ? 'Restore side panel' : 'Maximize side panel'}
            title={maximized ? 'Restore side panel' : 'Maximize side panel'}
          >
            {maximized ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </motion.button>
        )}
        <motion.button
          layout
          type="button"
          onClick={closeWorkbench}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.92 }}
          transition={motionPreset.spring}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Hide side panel"
          title="Hide side panel"
        >
          <X size={15} />
        </motion.button>
      </motion.header>
      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
        <AnimatePresence initial={false}>
          {activeTool === null && (
            <WorkbenchLauncher
              mode={mode}
              sessionId={sessionId}
              workspace={workspace}
            />
          )}
        </AnimatePresence>
        {children}
      </div>
    </motion.aside>
      )}
    </AnimatePresence>
  )
}

function WorkbenchLauncher(context: WorkbenchContext) {
  const openTool = useUIStore((state) => state.openWorkbenchTool)
  const motionPreset = useMotionPreset()
  const availableTools = WORKBENCH_TOOL_ORDER.filter((tool) =>
    isWorkbenchToolEnabled(tool, context),
  )

  return (
    <motion.div
      key="workbench-launcher"
      initial={{ opacity: 0, scale: 0.985, y: 8 * motionPreset.distance }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.985, y: -6 * motionPreset.distance }}
      transition={motionPreset.transition}
      className="absolute inset-0 flex items-center justify-center overflow-y-auto px-6 py-10"
    >
      <motion.div layout className="w-full max-w-xl space-y-2">
        {availableTools.map((tool, index) => {
          const meta = WORKBENCH_TOOLS[tool]
          const Icon = meta.icon
          return (
            <motion.button
              type="button"
              key={tool}
              onClick={() => openTool(tool)}
              initial={{ opacity: 0, y: 8 * motionPreset.distance }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...motionPreset.transition, delay: staggerDelay(motionPreset, index) }}
              whileHover={{ x: 3 * motionPreset.distance, scale: 1.006 }}
              whileTap={{ scale: 0.985 }}
              className="group flex w-full items-center gap-3 rounded-xl border border-transparent bg-(--bg-card) px-4 py-3.5 text-left shadow-sm transition-colors hover:border-(--color-border-strong) hover:bg-(--bg-key)"
            >
              <Icon
                size={18}
                className="shrink-0 text-(--color-text-muted) group-hover:text-(--color-text)"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-(--color-text)">
                  {meta.label}
                </span>
                <span className="block truncate text-xs text-(--color-text-subtle)">
                  {meta.description}
                </span>
              </span>
              {meta.shortcut && (
                <kbd className="shrink-0 rounded-full bg-(--bg-key) px-2 py-1 font-mono text-[10px] text-(--color-text-muted)">
                  {meta.shortcut}
                </kbd>
              )}
            </motion.button>
          )
        })}
      </motion.div>
    </motion.div>
  )
}

interface WorkbenchSurfaceProps {
  tool: WorkbenchTool
  children: ReactNode
}

export function WorkbenchSurface({ tool, children }: WorkbenchSurfaceProps) {
  const tabs = useUIStore((state) => state.workbenchTabs)
  const activeTool = useUIStore((state) => state.activeWorkbenchTool)
  const mounted = tabs.some((tab) => tab.tool === tool)
  const motionPreset = useMotionPreset()
  if (!mounted) return null
  const active = activeTool === tool

  return (
    <motion.section
      initial={{
        opacity: active ? 1 : 0,
        x: active ? 0 : 8 * motionPreset.distance,
        scale: active ? 1 : 0.995,
        visibility: active ? 'visible' : 'hidden',
      }}
      animate={active
        ? { opacity: 1, x: 0, scale: 1, visibility: 'visible' }
        : {
            opacity: 0,
            x: 8 * motionPreset.distance,
            scale: 0.995,
            transitionEnd: { visibility: 'hidden' },
          }}
      transition={motionPreset.transition}
      className={cn(
        'absolute inset-0 min-h-0 min-w-0 overflow-hidden',
        !active && 'pointer-events-none',
      )}
      style={{ zIndex: active ? 1 : 0 }}
      aria-hidden={!active}
    >
      {children}
    </motion.section>
  )
}
