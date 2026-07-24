/**
 * Provider brand marks shared by Settings → Providers and the model picker.
 * Keep ids aligned with ``app.agent.providers.catalog``.
 */
import { cn } from '@/lib/utils'

interface ProviderBrand {
  iconClass: string
  tagline?: string
}

const PROVIDER_BRANDS: Record<string, ProviderBrand> = {
  anthropic: { iconClass: 'bg-[#D4A574]/15 text-[#D4A574] ring-[#D4A574]/20', tagline: 'Claude models' },
  googlegenai: { iconClass: 'bg-[#4285F4]/15 text-[#4285F4] ring-[#4285F4]/20', tagline: 'Gemini models' },
  openai: { iconClass: 'bg-[#10A37F]/15 text-[#10A37F] ring-[#10A37F]/20', tagline: 'GPT & reasoning' },
  openrouter: { iconClass: 'bg-[#8B5CF6]/15 text-[#8B5CF6] ring-[#8B5CF6]/20', tagline: 'Multi-provider router' },
  zai: { iconClass: 'bg-[#111827]/15 text-[#111827] dark:bg-white/10 dark:text-white/85 ring-[#111827]/20', tagline: 'GLM models' },
  nvidia: { iconClass: 'bg-[#76B900]/15 text-[#76B900] ring-[#76B900]/20', tagline: 'NVIDIA NIM' },
  xai: { iconClass: 'bg-[#E8E8E8]/20 text-(--color-text) ring-(--color-border)', tagline: 'Grok models' },
  deepseek: { iconClass: 'bg-[#4D6BFE]/15 text-[#4D6BFE] ring-[#4D6BFE]/20', tagline: 'DeepSeek models' },
  copilot: { iconClass: 'bg-[#6E40C9]/15 text-[#6E40C9] ring-[#6E40C9]/20', tagline: 'GitHub Copilot' },
  codex: { iconClass: 'bg-[#10A37F]/15 text-[#10A37F] ring-[#10A37F]/20', tagline: 'Codex CLI' },
  ollama: { iconClass: 'bg-white/10 text-white/80 ring-white/15', tagline: 'Local inference' },
  router9: { iconClass: 'bg-[#60A5FA]/15 text-[#60A5FA] ring-[#60A5FA]/20', tagline: 'Model router' },
  cliproxy: { iconClass: 'bg-[#F59E0B]/15 text-[#F59E0B] ring-[#F59E0B]/20', tagline: 'CLI proxy' },
  xiaomi: { iconClass: 'bg-[#FF6900]/15 text-[#FF6900] ring-[#FF6900]/20', tagline: 'MiLM models' },
  kimi: { iconClass: 'bg-[#7C3AED]/15 text-[#7C3AED] ring-[#7C3AED]/20', tagline: 'Moonshot AI' },
  foundry: { iconClass: 'bg-[#0078D4]/15 text-[#0078D4] ring-[#0078D4]/20', tagline: 'Azure AI Foundry' },
  fci: { iconClass: 'bg-[#F26522]/15 text-[#F26522] ring-[#F26522]/20', tagline: 'FPT inference gateway' },
  bedrock: { iconClass: 'bg-[#FF9900]/15 text-[#FF9900] ring-[#FF9900]/20', tagline: 'AWS Bedrock' },
  vertexai: { iconClass: 'bg-[#4285F4]/15 text-[#4285F4] ring-[#4285F4]/20', tagline: 'Vertex AI' },
}

function getProviderBrand(id: string): ProviderBrand {
  return PROVIDER_BRANDS[id] ?? { iconClass: 'bg-(--bg-key) text-(--color-text-muted) ring-(--color-border)' }
}

function providerPrefix(modelOrProviderId: string): string {
  const colon = modelOrProviderId.indexOf(':')
  return (colon === -1 ? modelOrProviderId : modelOrProviderId.slice(0, colon)).toLowerCase()
}

function LogoMark({ id, size }: { id: string; size: number }) {
  switch (id) {
    case 'anthropic':
      return (
        <svg width={size} height={size} viewBox="0 0 256 176" fill="currentColor" aria-hidden="true">
          <path d="M147.487 0C147.487 0 217.568 175.78 217.568 175.78H256L185.919 0H147.487ZM70.071 0C70.071 0 0 175.78 0 175.78H39.179L53.51 138.866H126.818L141.146 175.78H180.325L110.254 0H70.071ZM66.183 106.221L90.162 44.447L114.142 106.221H66.183Z" />
        </svg>
      )
    case 'googlegenai':
    case 'vertexai':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 2.5c-1.8 3.4-3.2 5.7-5.8 8.4 1.7.1 3 .1 4.7-.3C9.2 14.2 8 16.4 6.8 21.5 10.2 18.6 12.4 16.3 15.5 13c-1.6-.1-2.7-.1-4.1.2C13.4 9.4 14.6 7.2 17.2 2.5 15.4 3.8 14 4.8 12 2.5Z" fill="currentColor" />
        </svg>
      )
    case 'openai':
    case 'codex':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.787a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.693zm2.01-3.023-.141-.085-4.784-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0-.393.681zm1.097-2.365 2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5z" />
        </svg>
      )
    case 'copilot':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
        </svg>
      )
    case 'ollama':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M12 2a4.5 4.5 0 0 1 4.5 4.5v1.1c1.7.4 3 1.9 3 3.8v1.4c0 1.5-.9 2.8-2.2 3.4.4 1.8.2 3.7-.7 5.3-.2.3-.6.4-.9.2-.3-.2-.4-.6-.2-.9.7-1.3.9-2.8.6-4.2-.1-.4-.4-.6-.8-.6H8.7c-.4 0-.7.2-.8.6-.3 1.4-.1 2.9.6 4.2.2.3.1.7-.2.9-.3.2-.7.1-.9-.2-.9-1.6-1.1-3.5-.7-5.3C5.4 15.6 4.5 14.3 4.5 12.8v-1.4c0-1.9 1.3-3.4 3-3.8V6.5A4.5 4.5 0 0 1 12 2zm0 1.5A3 3 0 0 0 9 6.5v1h6v-1a3 3 0 0 0-3-3z" />
        </svg>
      )
    case 'openrouter':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M16.5 3.5 21 8l-4.5 4.5-1.4-1.4L17.2 9H13a5 5 0 0 0-5 5v2H6v-2a7 7 0 0 1 7-7h4.2l-2.1-2.1L16.5 3.5ZM7.5 20.5 3 16l4.5-4.5 1.4 1.4L6.8 15H11a5 5 0 0 0 5-5V8h2v2a7 7 0 0 1-7 7H6.8l2.1 2.1-1.4 1.4Z" />
        </svg>
      )
    case 'xai':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M4.5 3.75h3.2L12 10.2l4.3-6.45h3.2L13.9 12.3 20.5 20.25h-3.25L12 14.05l-5.25 6.2H3.5L10.1 12.3 4.5 3.75Z" />
        </svg>
      )
    case 'deepseek':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M4 6.5A4.5 4.5 0 0 1 8.5 2H14a8 8 0 0 1 0 16h-1.2l2.7 4H12l-2.8-4H8.5A4.5 4.5 0 0 1 4 13.5v-7Zm4.5-2.5A2.5 2.5 0 0 0 6 6.5v7A2.5 2.5 0 0 0 8.5 16H14a6 6 0 0 0 0-12H8.5Z" />
        </svg>
      )
    case 'nvidia':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M8.4 15.6c2.8 0 5.8-1.2 7.9-3.2.2-.2.5.1.3.3-2.3 2.5-5.9 4.2-9.2 4.2-3.5 0-5.4-1.8-5.4-4.2 0-2.5 1.9-3.7 4.8-3.7 1.1 0 2.4.2 3.5.5-.1-.6-.1-1.2-.1-1.7 0-.4 0-.8.1-1.1H2.8c-.3 0-.4-.3-.3-.5.8-1.4 3.3-2.4 6.2-2.4 4.3 0 7.5 2.3 7.5 5.7 0 .5-.1 1.1-.2 1.6 1.4.6 2.3 1.5 2.3 2.9 0 2.7-2.4 4.6-6.4 4.6-3.1 0-5.9-1.2-7.5-2.6-.2-.2 0-.5.3-.4 1.2.6 3.1 1.2 4.7 1.2Zm.6-5.8c-1.8 0-2.9.7-2.9 1.9 0 1.3 1.2 2.1 3.1 2.1 1.5 0 2.9-.4 3.9-1-.9-.4-2.2-.9-4.1-1z" />
        </svg>
      )
    case 'bedrock':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M12 2 3.5 7v10L12 22l8.5-5V7L12 2Zm0 2.3 6.2 3.6v.2L12 11.8 5.8 8.1v-.2L12 4.3ZM5.2 9.8l5.8 3.4v6.7l-5.8-3.4V9.8Zm7.8 10.1v-6.7l5.8-3.4v6.7l-5.8 3.4Z" />
        </svg>
      )
    case 'zai':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M5 5h14v2.4L9.8 17H19V19H5v-2.4L14.2 7H5V5Z" />
        </svg>
      )
    case 'router9':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
        </svg>
      )
    case 'cliproxy':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M20 18c1.1 0 1.99-.9 1.99-2L22 6c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2H0v2h24v-2h-4zM4 6h16v10H4V6z" />
        </svg>
      )
    case 'xiaomi':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M4 7.5A3.5 3.5 0 0 1 7.5 4h9A3.5 3.5 0 0 1 20 7.5v9a3.5 3.5 0 0 1-3.5 3.5h-9A3.5 3.5 0 0 1 4 16.5v-9ZM7.5 6A1.5 1.5 0 0 0 6 7.5v9A1.5 1.5 0 0 0 7.5 18h9a1.5 1.5 0 0 0 1.5-1.5v-9A1.5 1.5 0 0 0 16.5 6h-9Zm1 2.5h2V16h-2V8.5Zm3.5 0H14c1.7 0 3 1.1 3 2.9S15.7 14.3 14 14.3h-1v1.7h-2V8.5Zm2 4.1c.7 0 1.2-.4 1.2-1.2S14.7 10.2 14 10.2h-1v2.4h1Z" />
        </svg>
      )
    case 'kimi':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M6 4h2.2v7.2L14.6 4H17l-5.4 6.4L17.2 20h-2.5l-4.3-6.5-2.2 2.5V20H6V4Z" />
        </svg>
      )
    case 'foundry':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M2 2h9.5v9.5H2V2zm10.5 0H22v9.5h-9.5V2zM2 12.5h9.5V22H2v-9.5zm10.5 0H22V22h-9.5v-9.5z" />
        </svg>
      )
    case 'fci':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M4 5h16v2.2H9.2V11H18v2.2H9.2V19H4V5Z" />
        </svg>
      )
    default:
      return (
        <span className="font-bold text-sm">{id.charAt(0).toUpperCase()}</span>
      )
  }
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
  const svgSizes = { xs: 12, sm: 16, md: 20, lg: 24 } as const

  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center ring-1 transition-all',
        sizeClasses[size],
        brand.iconClass,
        className,
      )}
      aria-hidden="true"
      title={brand.tagline}
    >
      <LogoMark id={id} size={svgSizes[size]} />
    </div>
  )
}
