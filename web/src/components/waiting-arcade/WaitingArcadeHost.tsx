import { useEffect, useState } from 'react'
import { WaitingArcadePanel } from './WaitingArcadePanel'

export interface WaitingArcadeHostProps {
  isWorking: boolean
  sessionId: string | null
  mode: string
  hasUserActionGate: boolean
}

export function WaitingArcadeHost({
  isWorking,
  sessionId,
  mode,
  hasUserActionGate,
}: WaitingArcadeHostProps) {
  const [eligibleEpoch, setEligibleEpoch] = useState<number | null>(null)
  const [compactEpoch, setCompactEpoch] = useState<number | null>(null)
  const [openEpoch, setOpenEpoch] = useState<number | null>(null)
  const [eligibility, setEligibility] = useState(() => ({ key: '', epoch: 0 }))
  const [documentVisible, setDocumentVisible] = useState(() => document.visibilityState !== 'hidden')
  const supportedMode = mode === 'work' || mode === 'coding'
  const currentEligibilityKey = JSON.stringify([sessionId, mode, isWorking, hasUserActionGate, documentVisible])
  if (eligibility.key !== currentEligibilityKey) {
    setEligibility({ key: currentEligibilityKey, epoch: eligibility.epoch + 1 })
  }

  useEffect(() => {
    const updateVisibility = () => setDocumentVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', updateVisibility)
    return () => document.removeEventListener('visibilitychange', updateVisibility)
  }, [])

  useEffect(() => {
    if (!isWorking || !sessionId || !supportedMode || hasUserActionGate || !documentVisible) return
    const epoch = eligibility.epoch
    const timer = window.setTimeout(() => setEligibleEpoch(epoch), 1500)
    return () => window.clearTimeout(timer)
  }, [isWorking, sessionId, mode, supportedMode, hasUserActionGate, documentVisible, eligibility.epoch])

  useEffect(() => {
    if (eligibleEpoch !== eligibility.epoch) return
    const timer = window.setTimeout(() => setCompactEpoch(eligibility.epoch), 10_000)
    return () => window.clearTimeout(timer)
  }, [eligibleEpoch, eligibility.epoch])

  if (!sessionId) return null
  const eligible = isWorking
    && supportedMode
    && !hasUserActionGate
    && documentVisible
  const canOpen = eligible && eligibleEpoch === eligibility.epoch

  return (
    <WaitingArcadePanel
      key={sessionId}
      open={openEpoch === eligibility.epoch && canOpen}
      onOpenChange={(nextOpen) => setOpenEpoch(nextOpen && canOpen ? eligibility.epoch : null)}
      active={canOpen}
      launcherVisible={canOpen}
      launcherEmphasized={canOpen && (openEpoch === eligibility.epoch || compactEpoch !== eligibility.epoch)}
    />
  )
}
