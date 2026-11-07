import { cn } from "@/lib/utils";

/**
 * The evo mark (`public/evo.svg`, which stays the window and file icon) drawn
 * inline so its centre stroke takes the Accent colour from Settings.
 */
export function EvoLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="64 64 896 896" aria-hidden className={cn("shrink-0", className)}>
      <rect x="64" y="64" width="896" height="896" rx="200" fill="#171717" />
      <g
        transform="translate(512 512) scale(9.739) rotate(-30) scale(1.25)"
        fill="none"
        strokeWidth={8}
        strokeLinecap="round"
      >
        <path d="M8 -17H-9A8 8 0 0 0 -17 -9V5" stroke="#ffffff" />
        <path d="M8 -17H-9A8 8 0 0 0 -17 -9V5" stroke="#ffffff" transform="rotate(180)" />
        <path d="M-3 0H3" stroke="var(--brand)" />
      </g>
    </svg>
  );
}
