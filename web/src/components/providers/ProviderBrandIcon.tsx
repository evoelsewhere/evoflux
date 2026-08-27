/**
 * Provider brand icons — bundled locally as React components, no runtime fetches.
 *
 * SVG glyphs come from the LobeHub icon set (lobehub/lobe-icons, MIT) and are
 * vendored in ``web/src/assets/providers/``.  They are imported with
 * ``?react`` (vite-plugin-svgr) and rendered inline with ``fill="currentColor"``,
 * tinted via the provider's brand color — crisp at every size, theme-safe, and
 * fully offline (no CDN, no proxy issues).
 *
 * FCI uses the official multi-color FPT symbol rendered with <img>.
 *
 * Keep ids aligned with ``app.agent.providers.catalog``.  Providers without a
 * glyph fall back to a brand-colored initial letter.
 */
import type { ComponentType, SVGProps } from 'react'
import { cn } from '@/lib/utils'

import AnthropicGlyph from '@/assets/providers/anthropic.svg?react'
import AzureAIGlyph from '@/assets/providers/azureai.svg?react'
import BedrockGlyph from '@/assets/providers/bedrock.svg?react'
import DeepSeekGlyph from '@/assets/providers/deepseek.svg?react'
import GitHubCopilotGlyph from '@/assets/providers/githubcopilot.svg?react'
import GoogleGlyph from '@/assets/providers/google.svg?react'
import KimiGlyph from '@/assets/providers/kimi.svg?react'
import NvidiaGlyph from '@/assets/providers/nvidia.svg?react'
import OllamaGlyph from '@/assets/providers/ollama.svg?react'
import OpenAIGlyph from '@/assets/providers/openai.svg?react'
import OpenRouterGlyph from '@/assets/providers/openrouter.svg?react'
import QwenGlyph from '@/assets/providers/qwen.svg?react'
import XAIGlyph from '@/assets/providers/xai.svg?react'
import XiaomiMiMoGlyph from '@/assets/providers/xiaomimimo.svg?react'
import ZAIGlyph from '@/assets/providers/zai.svg?react'
import fptUrl from '@/assets/providers/fpt.svg?url'

type Glyph = ComponentType<SVGProps<SVGSVGElement>>

interface ProviderBrand {
  /** Hex brand color used for the glyph + tinted background/ring. */
  color: string
  /** Inline SVG component (rendered with fill=currentColor). */
  Glyph?: Glyph
  /** Full-color image URL (takes precedence over Glyph). */
  imageUrl?: string
  tagline?: string
}

const PROVIDER_BRANDS: Record<string, ProviderBrand> = {
  anthropic: { color: '#D4A574', Glyph: AnthropicGlyph, tagline: 'Claude models' },
  googlegenai: { color: '#4285F4', Glyph: GoogleGlyph, tagline: 'Gemini models' },
  vertexai: { color: '#4285F4', Glyph: GoogleGlyph, tagline: 'Vertex AI' },
  openai: { color: '#10A37F', Glyph: OpenAIGlyph, tagline: 'GPT & reasoning' },
  qwencloud: { color: '#6F69F7', Glyph: QwenGlyph, tagline: 'QwenCloud models' },
  codex: { color: '#10A37F', Glyph: OpenAIGlyph, tagline: 'Codex CLI' },
  openrouter: { color: '#8B5CF6', Glyph: OpenRouterGlyph, tagline: 'Multi-provider router' },
  zai: { color: '#4B5563', Glyph: ZAIGlyph, tagline: 'GLM models' },
  nvidia: { color: '#76B900', Glyph: NvidiaGlyph, tagline: 'NVIDIA NIM' },
  xai: { color: '#9CA3AF', Glyph: XAIGlyph, tagline: 'Grok models' },
  deepseek: { color: '#4D6BFE', Glyph: DeepSeekGlyph, tagline: 'DeepSeek models' },
  copilot: { color: '#6E40C9', Glyph: GitHubCopilotGlyph, tagline: 'GitHub Copilot' },
  ollama: { color: '#9CA3AF', Glyph: OllamaGlyph, tagline: 'Local inference' },
  xiaomi: { color: '#FF6900', Glyph: XiaomiMiMoGlyph, tagline: 'MiLM models' },
  kimi: { color: '#7C3AED', Glyph: KimiGlyph, tagline: 'Moonshot AI' },
  foundry: { color: '#0078D4', Glyph: AzureAIGlyph, tagline: 'Azure AI Foundry' },
  bedrock: { color: '#FF9900', Glyph: BedrockGlyph, tagline: 'AWS Bedrock' },
  fci: { color: '#F26522', imageUrl: fptUrl, tagline: 'FPT inference gateway' },
  // No glyph available — these fall back to the initial letter.
  router9: { color: '#60A5FA', tagline: 'Model router' },
  cliproxy: { color: '#F59E0B', tagline: 'CLI proxy' },
}

const FALLBACK_COLOR = '#6B7280'

function getProviderBrand(id: string): ProviderBrand {
  return PROVIDER_BRANDS[id] ?? { color: FALLBACK_COLOR }
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

  const sizeClasses = {
    xs: 'h-5 w-5 rounded-md',
    sm: 'h-8 w-8 rounded-lg',
    md: 'h-10 w-10 rounded-xl',
    lg: 'h-12 w-12 rounded-xl',
  } as const
  const glyphPx = { xs: 12, sm: 18, md: 22, lg: 26 }[size]

  const containerStyle = {
    backgroundColor: `color-mix(in srgb, ${brand.color} 15%, transparent)`,
    // ring color via box-shadow so we don't fight Tailwind's ring utilities
    boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${brand.color} 25%, transparent)`,
  }

  const { Glyph, imageUrl } = brand

  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center transition-[background-color,border-color,opacity] duration-(--motion-fast)',
        sizeClasses[size],
        className,
      )}
      style={containerStyle}
      aria-hidden="true"
      title={brand.tagline ?? id}
    >
      {imageUrl ? (
        <img
          src={imageUrl}
          width={glyphPx}
          height={glyphPx}
          alt=""
          className="object-contain"
        />
      ) : Glyph ? (
        <Glyph
          width={glyphPx}
          height={glyphPx}
          style={{ color: brand.color }}
        />
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
