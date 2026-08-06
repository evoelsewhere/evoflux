/**
 * Root-owned mode navigation.
 *
 * Work and Coding have different route layouts and sidebar bodies,
 * but their primary navigation is application chrome. Keeping this component
 * above <Outlet /> means it survives cross-mode route changes, so the active
 * indicator can animate continuously instead of being recreated by every
 * sidebar.
 *
 * Desktop sidebars reserve the matching space with SidebarModeSlot /
 * SidebarModeRailSlot. Mobile drawers keep a local switcher because they are
 * transient overlays with their own open/close lifecycle.
 */

import { useLocation } from '@tanstack/react-router'
import { ModeSwitchRail, ModeSwitchTabs, type AppMode } from '@/components/ModeSwitchTabs'
import { usePlatform } from '@/hooks/use-platform'
import { DURATIONS, useMotionPreset } from '@/lib/motion'
import { appModeForPath } from '@/lib/mode-route'
import { useUIStore } from '@/stores/useUIStore'

export function PersistentModeNavigation() {
  const location = useLocation()
  const { isMacOverlay } = usePlatform()
  const motionPreset = useMotionPreset()
  const collapsed = useUIStore((state) => state.sidebarCollapsed)
  const sidebarWidth = useUIStore((state) => state.sidebarWidth)
  const settingsOpen = useUIStore((state) => state.settingsOpen)
  const active: AppMode | null = appModeForPath(location.pathname)

  if (!active || settingsOpen) return null

  const shellWidth = collapsed ? (isMacOverlay ? 70 : 56) : sidebarWidth
  const transitionDuration = DURATIONS.base * motionPreset.scale

  return (
    <div
      data-testid="persistent-mode-navigation"
      data-sidebar-width-follower
      style={{
        width: Math.max(0, shellWidth - 8),
        transition: `width ${transitionDuration}ms var(--ease-out)`,
      }}
      className="pointer-events-none fixed left-1 top-1 z-(--z-header) hidden md:block"
    >
      {collapsed ? (
        <div
          className={`pointer-events-auto flex w-full justify-center ${
            isMacOverlay ? 'pt-10' : 'pt-2'
          }`}
        >
          <ModeSwitchRail active={active} />
        </div>
      ) : (
        <div
          className={`pointer-events-auto w-full px-2 ${
            isMacOverlay ? 'pt-10' : 'pt-2'
          }`}
        >
          <ModeSwitchTabs active={active} />
        </div>
      )}
    </div>
  )
}
