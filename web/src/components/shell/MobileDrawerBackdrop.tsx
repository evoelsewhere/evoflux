/**
 * MobileDrawerBackdrop — dimmed scrim behind left-edge navigation drawers.
 * Composes with `useModalFocus` on the drawer panel (`data-modal-focus`).
 * Parent should mount inside `AnimatePresence` when the drawer is open.
 */

import { motion } from 'framer-motion'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

interface MobileDrawerBackdropProps {
  onClose: () => void
  closeLabel?: string
  className?: string
  /** Keep the scrim visible when the responsive drawer is used on desktop. */
  desktopVisible?: boolean
}

export function MobileDrawerBackdrop({
  onClose,
  closeLabel = 'Close navigation',
  className,
  desktopVisible = false,
}: MobileDrawerBackdropProps) {
  const preset = useMotionPreset()

  return (
    <motion.button
      type="button"
      key="mobile-drawer-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={preset.transition}
      aria-label={closeLabel}
      className={cn(
        'mobile-safe-top fixed inset-x-0 bottom-0 z-(--z-drawer) bg-(--color-overlay)',
        !desktopVisible && 'md:hidden',
        className,
      )}
      onClick={onClose}
    />
  )
}
