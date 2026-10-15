import { useEffect, useState } from 'react'
import type { ContentBlock } from '@/api/types'
import { useThemePreference } from '@/hooks/useThemePreference'
import { useMotionPreset } from '@/lib/motion'
import { useTeamStore } from '@/stores/useTeamStore'
import { DashboardArtifact } from './visual-artifact/DashboardArtifact'
import { MotionArtifact } from './visual-artifact/MotionArtifact'
import { Scene3DArtifact } from './visual-artifact/Scene3DArtifact'

export function VisualArtifactRenderer({ block }: { block: ContentBlock }) {
  const artifact = block.visualArtifact
  const { preference, resolved } = useThemePreference()
  const motionPreset = useMotionPreset()
  const [reducedMotion, setReducedMotion] = useState(() => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true)
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReducedMotion(media.matches)
    media.addEventListener('change', sync)
    return () => media.removeEventListener('change', sync)
  }, [])
  if (!artifact) return null
  const respectReducedMotion = reducedMotion || motionPreset.intensity === 'reduced'
  const onSendPrompt = (prompt: string) => {
    void useTeamStore.getState().sendMessage(prompt, undefined, { delivery: 'steer' })
  }
  if (artifact.kind === 'dashboard') return <DashboardArtifact artifact={artifact} theme={preference} reducedMotion={respectReducedMotion} onSendPrompt={onSendPrompt} />
  if (artifact.kind === 'motion') return <MotionArtifact artifact={artifact} theme={preference} reducedMotion={respectReducedMotion} />
  if (artifact.kind === 'scene3d') return <Scene3DArtifact artifact={artifact} reducedMotion={respectReducedMotion} resolvedTheme={resolved} />
  return <p className="text-sm text-(--color-text-subtle)">This visual artifact type is not supported.</p>
}
