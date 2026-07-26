/**
 * Provider brand icons sourced from the LobeHub icon set.
 *
 * Each provider renders as a CSS mask over a brand-colored background, so the
 * glyph always matches the brand color and works on both light and dark UI.
 * Mask URLs point at the monochrome SVGs in the lobe-icons GitHub repo:
 *
 *   https://raw.githubusercontent.com/lobehub/lobe-icons/refs/heads/master/packages/static-svg/icons/{id}.svg
 *
 * Keep ids aligned with ``app.agent.providers.catalog``.  Providers without a
 * LobeHub glyph fall back to a colored initial letter.
 */
import type { CSSProperties } from 'react'
import { cn } from '@/lib/utils'

const SVG_BASE =
  'https://raw.githubusercontent.com/lobehub/lobe-icons/refs/heads/master/packages/static-svg/icons'

interface ProviderBrand {
  /** Hex brand color used for the glyph + tinted background/ring. */
  color: string
  /** LobeHub icon id when it differs from the EvoFlux provider id. */
  lobeId?: string
  tagline?: string
}

const PROVIDER_BRANDS: Record<string, ProviderBrand> = {
  anthropic: { color: '#D4A574', tagline: 'Claude models' },
  googlegenai: { color: '#4285F4', lobeId: 'google', tagline: 'Gemini models' },
  vertexai: { color: '#4285F4', lobeId: 'google', tagline: 'Vertex AI' },
  openai: { color: '#10A37F', tagline: 'GPT & reasoning' },
  codex: { color: '#10A37F', tagline: 'Codex CLI' },
  openrouter: { color: '#8B5CF6', tagline: 'Multi-provider router' },
  zai: { color: '#4B5563', tagline: 'GLM models' },
  nvidia: { color: '#76B900', tagline: 'NVIDIA NIM' },
  xai: { color: '#9CA3AF', tagline: 'Grok models' },
  deepseek: { color: '#4D6BFE', tagline: 'DeepSeek models' },
  copilot: { color: '#6E40C9', lobeId: 'githubcopilot', tagline: 'GitHub Copilot' },
  ollama: { color: '#9CA3AF', tagline: 'Local inference' },
  xiaomi: { color: '#FF6900', lobeId: 'xiaomimimo', tagline: 'MiLM models' },
  kimi: { color: '#7C3AED', tagline: 'Moonshot AI' },
  foundry: { color: '#0078D4', lobeId: 'azureai', tagline: 'Azure AI Foundry' },
  bedrock: { color: '#FF9900', tagline: 'AWS Bedrock' },
  // No LobeHub glyph available — these fall back to the initial letter.
  router9: { color: '#60A5FA', lobeId: '', tagline: 'Model router' },
  cliproxy: { color: '#F59E0B', lobeId: '', tagline: 'CLI proxy' },
  fci: { color: '#F26522', lobeId: '', tagline: 'FPT inference gateway' },
}

const FALLBACK_COLOR = '#6B7280'

function getProviderBrand(id: string): ProviderBrand {
  return PROVIDER_BRANDS[id] ?? { color: FALLBACK_COLOR, lobeId: '' }
}

function providerPrefix(modelOrProviderId: string): string {
  const colon = modelOrProviderId.indexOf(':')
  return (colon === -1 ? modelOrProviderId : modelOrProviderId.slice(0, colon)).toLowerCase()
}

export function ProviderBrandIcon({
  providerId,
  size = 'md',
  className,
}: {
  providerId: string
  size?: 'sm' | 'md' | 'lg' | 'xs'
  className?: string
}) {
  const id = providerPrefix(providerId)
  const brand = getProviderBrand(id)
  const lobeId = brand.lobeId ?? id

  const sizeClasses = {
    xs: 'h-5 w-5 rounded-md',
    sm: 'h-8 w-8 rounded-lg',
    md: 'h-10 w-10 rounded-xl',
    lg: 'h-12 w-12 rounded-xl',
  } as const
  const glyphPx = { xs: 12, sm: 18, md: 22, lg: 26 }[size]

  const containerStyle: CSSProperties = {
    backgroundColor: `color-mix(in srgb, ${brand.color} 15%, transparent)`,
    // ring color via box-shadow so we don't fight Tailwind's ring utilities
    boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${brand.color} 25%, transparent)`,
  }

  const glyphStyle: CSSProperties = {
    width: glyphPx,
    height: glyphPx,
    backgroundColor: brand.color,
    WebkitMaskImage: `url(${SVG_BASE}/${lobeId}.svg)`,
    maskImage: `url(${SVG_BASE}/${lobeId}.svg)`,
    WebkitMaskSize: 'contain',
    maskSize: 'contain',
    WebkitMaskRepeat: 'no-repeat',
    maskRepeat: 'no-repeat',
    WebkitMaskPosition: 'center',
    maskPosition: 'center',
  }

  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center transition-all',
        sizeClasses[size],
        className,
      )}
      style={containerStyle}
      aria-hidden="true"
      title={brand.tagline ?? id}
    >
      {lobeId ? (
        <div style={glyphStyle} />
      ) : (
        <span
          className="font-bold"
          style={{ color: brand.color, fontSize: '0.9em', lineHeight: 1 }}
        >
          {id.charAt(0).toUpperCase()}
        </span>
      )}
    </div>
  )
}
