import { useEffect } from 'react'

export function useModalFocus(open: boolean, onClose?: () => void) {
  useEffect(() => {
    if (!open) return
    const previousActive = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const getDialog = () => {
      const dialogs = document.querySelectorAll<HTMLElement>('[data-modal-focus="true"]')
      return dialogs[dialogs.length - 1] ?? null
    }
    const isVisible = (el: HTMLElement) => el.getClientRects().length > 0
    const focusFirst = () => {
      const dialog = getDialog()
      const target = dialog?.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      if (target && isVisible(target)) target.focus()
    }
    const id = requestAnimationFrame(focusFirst)

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose?.()
        return
      }
      if (event.key !== 'Tab') return
      const dialog = getDialog()
      if (!dialog) return
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((el) => !el.hasAttribute('disabled') && isVisible(el))
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      cancelAnimationFrame(id)
      document.removeEventListener('keydown', handleKeyDown)
      if (previousActive?.isConnected) previousActive.focus()
    }
  }, [open, onClose])
}
