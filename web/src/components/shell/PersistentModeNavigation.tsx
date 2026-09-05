/**
 * Root-owned mode navigation.
 *
 * Work and Coding have different route layouts and sidebar bodies,
 * but their primary navigation is application chrome. Keeping this component
 * above <Outlet /> means it survives cross-mode route changes, so the active
 * indicator can animate continuously instead of being recreated by every
 * sidebar.
 *
 * Expanded desktop sidebars reserve matching space with SidebarModeSlot.
 * Mobile drawers keep a local switcher because they are transient overlays
 * with their own open/close lifecycle.
 */

import { useLocation } from '@tanstack/react-router'
import { ModeSwitchTabs, type AppMode } from '@/components/ModeSwitchTabs'
import { usePlatform } from '@/hooks/use-platform'
import { DURATIONS, useMotionPreset } from '@/lib/motion'
import { appModeForPath } from '@/lib/mode-route'
import { useUIStore } from '@/stores/useUIStore'

export function PersistentModeNavigation() {
  const location = useLocation()
  const { isMacOverlay } = usePlatform()
  const motionPreset = useMotionPreset()
  const collapsed = useUIStore((state) => state.sidebarCollapsed)
  const sidebarOverlay = useUIStore((state) => state.sidebarOverlay)
  const sidebarWidth = useUIStore((state) => state.sidebarWidth)
  const settingsOpen = useUIStore((state) => state.settingsOpen)
  const active: AppMode | null = appModeForPath(location.pathname)

  if (!active || settingsOpen || sidebarOverlay || collapsed) return null

  const transitionDuration = DURATIONS.base * motionPreset.scale

  // The strip is anchored to the sidebar card's own top edge (the shell's
  // 2px inset) and inset by the same 6px column the sidebar rows use, so it
  // lands exactly on the SidebarModeSlot each sidebar reserves for it —
  // `top-0.5 + pt-1.5` here must stay equal to the slot's own top padding.
  return (
    <div
      data-testid="persistent-mode-navigation"
      data-sidebar-width-follower
      style={{
        width: Math.max(0, sidebarWidth - 8),
        transition: `width ${transitionDuration}ms var(--ease-out)`,
      }}
      className="pointer-events-none fixed left-1 top-0.5 z-(--z-header) hidden md:block"
    >
      <div
        className={`pointer-events-auto w-full px-0.5 ${
          isMacOverlay ? 'pt-10' : 'pt-1.5'
        }`}
      >
        <ModeSwitchTabs active={active} compact />
      </div>
    </div>
  )
}
