import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Maximize2, Menu, Minimize2, Plus, X } from 'lucide-react'
import { useResizableWidth } from '@/hooks/use-resizable-width'
import { useIsMobile } from '@/hooks/use-mobile'
import { staggerDelay, useMotionPreset } from '@/lib/motion'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { cn } from '@/lib/utils'
import { formatShortcutLabel } from '@/lib/keyboard-shortcuts'
import {
  loadBrowserPreferences,
  subscribeBrowserPreferences,
} from '@/components/BrowserViewer/browserPreferences'
import {
  type WorkbenchTab,
  type WorkbenchTool,
  useUIStore,
} from '@/stores/useUIStore'
import {
  isWorkbenchToolEnabled,
  WORKBENCH_TOOL_ORDER,
  WORKBENCH_TOOLS,
  type WorkbenchContext,
} from './tools'

interface WorkbenchDockProps extends WorkbenchContext {
  children: ReactNode
  className?: string
  /** Opens responsive navigation while the Workbench occupies the canvas. */
  onOpenSidebar?: () => void
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
  onOpenSidebar,
}: WorkbenchDockProps) {
  const open = useUIStore((state) => state.workbenchOpen)
  const tabs = useUIStore((state) => state.workbenchTabs)
  const activeTabId = useUIStore((state) => state.activeWorkbenchTabId)
  const activeTool = useUIStore((state) => state.activeWorkbenchTool)
  const maximized = useUIStore((state) => state.workbenchMaximized)
  const selectTab = useUIStore((state) => state.selectWorkbenchTab)
  const closeTab = useUIStore((state) => state.closeWorkbenchTab)
  const closeWorkbench = useUIStore((state) => state.closeWorkbench)
  const showLauncher = useUIStore((state) => state.showWorkbenchLauncher)
  const toggleMaximized = useUIStore((state) => state.toggleWorkbenchMaximized)
  const motionPreset = useMotionPreset()
  const isMobile = useIsMobile()
  const resizable = useResizableWidth({
    storageKey: STORAGE_KEYS.panels.workbench,
    defaultWidth: 540,
    minWidth: 360,
    maxWidth: 1080,
    edge: 'left',
    disabled: maximized || isMobile,
  })
  const closeTabAndResources = (tabId: string) => {
    window.dispatchEvent(new CustomEvent('evoflux:workbench-tab-close', {
      detail: { tabId },
    }))
    closeTab(tabId)
  }

  // Closing must release the flex column immediately. An exit animation keeps
  // the measured-width aside mounted and makes the conversation resize late.
  if (!open) return null

  return (
    <motion.aside
      key="workbench-dock"
      initial={{
        opacity: 0,
      }}
      animate={{
        opacity: 1,
      }}
      transition={motionPreset.transition}
      style={{
        width: maximized || isMobile ? '100%' : resizable.width,
      }}
      className={cn(
        'flex h-full min-h-0 min-w-0 flex-col overflow-hidden border-l border-(--color-border-strong) bg-(--bg-page)',
        isMobile
          ? 'mobile-safe-top fixed inset-x-0 bottom-0 z-(--z-overlay) h-auto w-full max-w-none'
          : 'relative shrink-0',
        maximized && !isMobile && 'flex-1',
        className,
      )}
      aria-label="Workbench tools"
    >
      {!maximized && !isMobile && (
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
        className="flex h-11 shrink-0 items-center gap-1 px-2"
      >
        {maximized && onOpenSidebar && (
          <motion.button
            type="button"
            onClick={onOpenSidebar}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.92 }}
            transition={motionPreset.spring}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Open navigation"
            title="Open navigation"
          >
            <Menu size={15} />
          </motion.button>
        )}
        <motion.div className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
          <AnimatePresence initial={false}>
          {tabs.map((tab) => {
            const meta = WORKBENCH_TOOLS[tab.tool]
            const Icon = meta.icon
            const active = activeTabId === tab.id
            const sameToolTabs = tabs.filter((item) => item.tool === tab.tool)
            const sameToolIndex = sameToolTabs.findIndex((item) => item.id === tab.id)
            const label = tab.title
              ?? (sameToolTabs.length > 1
                ? `${meta.label} ${sameToolIndex + 1}`
                : meta.label)
            return (
              <motion.div
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
                  onClick={() => selectTab(tab.id)}
                  className="relative z-(--z-panel) flex h-full min-w-0 flex-1 items-center gap-1.5 pl-2 pr-1"
                >
                  <Icon size={14} className="shrink-0" />
                  <span className="truncate text-xs font-medium">{label}</span>
                </button>
                <button
                  type="button"
                  onClick={() => closeTabAndResources(tab.id)}
                  className={cn(
                    'relative z-(--z-panel) mr-1 flex h-5 w-5 shrink-0 items-center justify-center rounded text-(--color-text-muted) transition-[opacity,background-color,color] hover:bg-(--bg-hover) hover:text-(--color-text) focus-visible:opacity-100 group-hover:opacity-100',
                    active ? 'opacity-100' : 'opacity-0',
                  )}
                  aria-label={`Close ${label}`}
                >
                  <X size={12} />
                </button>
              </motion.div>
            )
          })}
          </AnimatePresence>
          <motion.button
            type="button"
            onClick={showLauncher}
            whileHover={{ scale: 1.06 }}
            whileTap={{ scale: 0.92 }}
            transition={motionPreset.spring}
            className={cn(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors',
              activeTabId === null
                ? 'bg-(--bg-key) text-(--color-text)'
                : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
            )}
            aria-label="Choose side panel tool"
            title="Choose side panel tool"
          >
            <Plus size={16} />
          </motion.button>
        </motion.div>

        {activeTabId && !isMobile && (
          <motion.button
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
      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden border-t border-(--color-border)">
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
  )
}

function WorkbenchLauncher(context: WorkbenchContext) {
  const createTab = useUIStore((state) => state.createWorkbenchTab)
  const motionPreset = useMotionPreset()
  // Re-render when built-in browser preference flips so the Browser tile
  // appears/disappears without remounting the whole dock.
  const [builtInBrowserEnabled, setBuiltInBrowserEnabled] = useState(
    () => loadBrowserPreferences().enabled,
  )
  useEffect(
    () => subscribeBrowserPreferences((next) => setBuiltInBrowserEnabled(next.enabled)),
    [],
  )
  const availableTools = WORKBENCH_TOOL_ORDER.filter((tool) => {
    if (tool === 'browser' && !builtInBrowserEnabled) return false
    return isWorkbenchToolEnabled(tool, context)
  })

  return (
    <motion.div
      key="workbench-launcher"
      initial={{ opacity: 0, scale: 0.985, y: 8 * motionPreset.distance }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.985, y: -6 * motionPreset.distance }}
      transition={motionPreset.transition}
      className="absolute inset-0 flex items-center justify-center overflow-y-auto px-5 py-8"
    >
      <motion.div layout className="w-full max-w-lg space-y-1.5">
        {availableTools.map((tool, index) => {
          const meta = WORKBENCH_TOOLS[tool]
          const Icon = meta.icon
          return (
            <motion.button
              type="button"
              key={tool}
              onClick={() => createTab(tool)}
              initial={{ opacity: 0, y: 8 * motionPreset.distance }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...motionPreset.transition, delay: staggerDelay(motionPreset, index) }}
              whileHover={{ x: 3 * motionPreset.distance, scale: 1.006 }}
              whileTap={{ scale: 0.985 }}
              className="group flex w-full items-center gap-2.5 rounded-lg border border-transparent bg-(--bg-card) px-3 py-2 text-left shadow-sm transition-colors hover:border-(--color-border-strong) hover:bg-(--bg-key)"
            >
              <Icon
                size={16}
                className="shrink-0 text-(--color-text-muted) group-hover:text-(--color-text)"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-(--color-text)">
                  {meta.label}
                </span>
                <span className="block truncate text-[11px] leading-4 text-(--color-text-subtle)">
                  {meta.description}
                </span>
              </span>
              {meta.shortcut && (
                <kbd className="shrink-0 rounded-md border border-(--color-border) bg-(--bg-key) px-1.5 py-1 font-sans text-[11px] font-medium leading-none tracking-normal text-(--color-text-muted)">
                  {formatShortcutLabel(meta.shortcut)}
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
  children: ReactNode | ((tab: WorkbenchTab, active: boolean) => ReactNode)
}

export function WorkbenchSurface({ tool, children }: WorkbenchSurfaceProps) {
  const tabs = useUIStore((state) => state.workbenchTabs)
  const activeTabId = useUIStore((state) => state.activeWorkbenchTabId)
  const toolTabs = tabs.filter((tab) => tab.tool === tool)
  const motionPreset = useMotionPreset()
  return toolTabs.map((tab) => {
    const active = activeTabId === tab.id
    return (
      <motion.section
        key={tab.id}
        initial={{
          opacity: active ? 1 : 0,
          visibility: active ? 'visible' : 'hidden',
        }}
        animate={active
          ? { opacity: 1, visibility: 'visible' }
          : {
              opacity: 0,
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
        {typeof children === 'function' ? children(tab, active) : children}
      </motion.section>
    )
  })
}
