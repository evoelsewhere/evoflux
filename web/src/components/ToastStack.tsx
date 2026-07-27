/**
 * ToastStack — renders all toasts from ``useToastStore`` at the bottom
 * edge: bottom-right on desktop, bottom-centered on mobile. Auto-dismiss
 * is driven by the store.
 *
 * Swipe right or down to dismiss.
 */
import { AnimatePresence, motion, useMotionValue, useTransform } from 'framer-motion'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'
import { useToastStore, type Toast } from '@/stores/useToastStore'
import { reducedMotionTransition, useMotionPreset } from '@/lib/motion'

const TONE_STYLES: Record<
  Toast['tone'],
  { icon: React.ComponentType<{ size?: number; className?: string }>; iconClass: string }
> = {
  success: {
    icon: CheckCircle2,
    iconClass: 'text-(--color-success) opacity-60',
  },
  error: {
    icon: AlertCircle,
    iconClass: 'text-(--color-error)',
  },
  info: {
    icon: Info,
    iconClass: 'text-(--color-text-muted)',
  },
}

// Threshold (px) past which a drag is treated as a dismiss gesture
const SWIPE_THRESHOLD = 60

interface ToastItemProps {
  t: Toast
  dismiss: (id: string) => void
}

function ToastItem({ t, dismiss }: ToastItemProps) {
  const { icon: Icon, iconClass } = TONE_STYLES[t.tone]
  const preset = useMotionPreset()
  const reduced = preset.intensity === 'reduced'

  const x = useMotionValue(0)
  const y = useMotionValue(0)
  // Fade out as the user drags away
  const opacity = useTransform([x, y], ([latestX, latestY]: number[]) => {
    const dist = Math.max(Math.abs(latestX), Math.abs(latestY))
    return Math.max(0, 1 - dist / (SWIPE_THRESHOLD * 1.5))
  })

  function handleDragEnd() {
    const dx = x.get()
    const dy = y.get()
    // Dismiss on swipe right or swipe down
    if (dx > SWIPE_THRESHOLD || dy > SWIPE_THRESHOLD) {
      dismiss(t.id)
    }
  }

  return (
    <motion.div
      key={t.id}
      layout
      style={{ x, y, opacity }}
      variants={{
        enter: reduced
          ? { opacity: 0 }
          : {
              opacity: 0,
              y: 12 * preset.distance,
              scale: 0.96,
              transition: reducedMotionTransition(reduced, preset.spring),
            },
        visible: reduced
          ? { opacity: 1 }
          : {
              opacity: 1,
              y: 0,
              scale: 1,
              transition: reducedMotionTransition(reduced, preset.spring),
            },
        exit: reduced
          ? { opacity: 0 }
          : {
              opacity: 0,
              x: 40 * preset.distance,
              scale: 0.96,
              transition: reducedMotionTransition(reduced, preset.transition),
            },
      }}
      initial="enter"
      animate="visible"
      exit="exit"
      drag
      dragConstraints={{ left: 0, right: 200, top: 0, bottom: 200 }}
      dragElastic={{ left: 0.05, right: 0.4, top: 0.05, bottom: 0.4 }}
      dragMomentum={false}
      onDragEnd={handleDragEnd}
      whileDrag={{ cursor: 'grabbing' }}
      className="pointer-events-auto flex cursor-grab items-start gap-3 rounded-xl bg-(--bg-key) p-3 shadow-xl ring-1 ring-(--color-border) select-none"
      role="status"
      aria-live="polite"
    >
      <Icon size={16} className={`mt-0.5 shrink-0 ${iconClass}`} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-(--color-text)">{t.title}</p>
        {t.description && (
          <p className="mt-0.5 text-xs text-(--color-text-muted)">{t.description}</p>
        )}
      </div>
      <button
        onClick={() => dismiss(t.id)}
        aria-label="Dismiss"
        className="shrink-0 rounded-md p-1 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
      >
        <X size={12} />
      </button>
    </motion.div>
  )
}

export function ToastStack() {
  const toasts = useToastStore((s) => s.toasts)
  const dismiss = useToastStore((s) => s.dismiss)

  return (
    <div className="mobile-safe-toast pointer-events-none fixed z-(--z-toast) flex w-auto flex-col items-end gap-2 sm:w-full sm:max-w-sm">
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <ToastItem key={t.id} t={t} dismiss={dismiss} />
        ))}
      </AnimatePresence>
    </div>
  )
}
