/**
 * RemoteControlPolicyDialog — the policy warning shown on entering
 * Settings → Remote Control, before the page can be used.
 *
 * Remote Control hands a device on the tailnet the same reach into this
 * computer as sitting at it, so the owner confirms what that means (and
 * that their organization allows it) first. "I understand" continues;
 * "Go back", Escape and the outside click all leave the page. Ticking
 * "Don't show this again" remembers the acknowledgement on this machine.
 */
import { Building2, Power, ShieldAlert, Smartphone, TerminalSquare, type LucideIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { acknowledgeRemoteControlPolicy } from '@/lib/remote-control-policy'

const POLICY_POINTS: Array<{ icon: LucideIcon; title: string; text: string }> = [
  {
    icon: TerminalSquare,
    title: 'It acts as you',
    text: 'Agents started from the remote device run with this computer’s access: workspaces, shell, browser and connected accounts.',
  },
  {
    icon: Smartphone,
    title: 'Only your own devices',
    text: 'Use it only from devices you own and control, on your own tailnet. Do not share the Tailscale account it signs in with.',
  },
  {
    icon: Building2,
    title: 'Follow your organization’s policy',
    text: 'On a work computer, confirm that remote access to it is allowed before you turn this on.',
  },
  {
    icon: Power,
    title: 'You stay in control',
    text: 'It stops when EvoFlux quits, and you can release the connected device from this page at any time.',
  },
]

export function RemoteControlPolicyDialog({
  open,
  onAccept,
  onLeave,
}: {
  open: boolean
  onAccept: () => void
  onLeave: () => void
}) {
  const [remember, setRemember] = useState(false)

  const accept = () => {
    if (remember) acknowledgeRemoteControlPolicy()
    onAccept()
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onLeave()
      }}
    >
      <DialogContent showCloseButton={false} className="gap-0 p-0 sm:max-w-md">
        <DialogHeader className="gap-2 px-5 pb-4 pt-5">
          <div className="flex size-10 items-center justify-center rounded-xl bg-(--color-warning)/12 text-(--color-warning)">
            <ShieldAlert size={20} aria-hidden="true" />
          </div>
          <DialogTitle className="mt-1 text-base">Before you use Remote Control</DialogTitle>
          <DialogDescription>
            Remote Control lets one device on your tailnet drive EvoFlux on this computer — the same agents, tools
            and files you can reach here.
          </DialogDescription>
        </DialogHeader>

        <ul className="space-y-3 border-y border-(--color-border-subtle) px-5 py-4">
          {POLICY_POINTS.map(({ icon: Icon, title, text }) => (
            <li key={title} className="flex gap-3">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-(--bg-key) text-(--color-text-muted)">
                <Icon size={14} aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <p className="text-xs font-medium text-(--color-text)">{title}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-(--color-text-muted)">{text}</p>
              </div>
            </li>
          ))}
        </ul>

        <DialogFooter className="mx-0 mb-0 flex-col items-stretch gap-3 border-t-0 bg-transparent px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-(--color-text-muted)">
            <input
              type="checkbox"
              checked={remember}
              onChange={(event) => setRemember(event.target.checked)}
              className="size-3.5 accent-(--color-accent)"
            />
            Don’t show this again
          </label>
          <div className="flex gap-2 sm:justify-end">
            <Button variant="ghost" onClick={onLeave}>
              Go back
            </Button>
            <Button autoFocus onClick={accept}>
              I understand
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
