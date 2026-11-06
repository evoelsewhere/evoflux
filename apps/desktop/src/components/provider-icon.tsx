// Provider brand marks, as EvoFlux draws them (ProviderBrandIcon.tsx):
// a monochrome glyph tinted with the brand colour on a faint tile of the same
// colour. Glyphs are vendored SVGs (see assets/providers/README.md) applied as
// a CSS mask, so they take any colour without an SVG loader. A provider with
// no mark shows its initials.

import type * as React from "react";
import { cn } from "@/lib/utils";

import anthropic from "@/assets/providers/anthropic.svg?url";
import azureai from "@/assets/providers/azureai.svg?url";
import bedrock from "@/assets/providers/bedrock.svg?url";
import deepseek from "@/assets/providers/deepseek.svg?url";
import githubcopilot from "@/assets/providers/githubcopilot.svg?url";
import google from "@/assets/providers/google.svg?url";
import kimi from "@/assets/providers/kimi.svg?url";
import nvidia from "@/assets/providers/nvidia.svg?url";
import ollama from "@/assets/providers/ollama.svg?url";
import openai from "@/assets/providers/openai.svg?url";
import openrouter from "@/assets/providers/openrouter.svg?url";
import qwen from "@/assets/providers/qwen.svg?url";
import xai from "@/assets/providers/xai.svg?url";
import xiaomimimo from "@/assets/providers/xiaomimimo.svg?url";
import zai from "@/assets/providers/zai.svg?url";

interface Brand {
  /** Brand colour for the glyph and its tile. */
  color: string;
  /** Monochrome glyph, tinted with `color`. */
  glyph?: string;
  /** Full-colour image, drawn as is. */
  image?: string;
}

const BRANDS: Record<string, Brand> = {
  anthropic: { color: "#D4A574", glyph: anthropic },
  openai: { color: "#10A37F", glyph: openai },
  codex: { color: "#10A37F", glyph: openai },
  googlegenai: { color: "#4285F4", glyph: google },
  vertexai: { color: "#4285F4", glyph: google },
  xiaomi: { color: "#FF6900", glyph: xiaomimimo },
  deepseek: { color: "#4D6BFE", glyph: deepseek },
  openrouter: { color: "#8B5CF6", glyph: openrouter },
  qwencloud: { color: "#6F69F7", glyph: qwen },
  zai: { color: "#71717A", glyph: zai },
  zhipuai: { color: "#71717A", glyph: zai },
  kimi: { color: "#7C3AED", glyph: kimi },
  moonshot: { color: "#7C3AED", glyph: kimi },
  nvidia: { color: "#76B900", glyph: nvidia },
  xai: { color: "#9CA3AF", glyph: xai },
  copilot: { color: "#6E40C9", glyph: githubcopilot },
  ollama: { color: "#9CA3AF", glyph: ollama },
  foundry: { color: "#0078D4", glyph: azureai },
  bedrock: { color: "#FF9900", glyph: bedrock },
};

/** Marks for every other provider follow the text colour. */
const NEUTRAL = "var(--muted-foreground)";

const SIZES = {
  xs: { box: "size-4 rounded", glyph: 11, text: "text-[7px]" },
  sm: { box: "size-7 rounded-md", glyph: 16, text: "text-[10px]" },
  md: { box: "size-9 rounded-lg", glyph: 20, text: "text-[11px]" },
  lg: { box: "size-11 rounded-xl", glyph: 24, text: "text-xs" },
} as const;

function initials(label: string): string {
  const words = label.replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : label.slice(0, 2)).toUpperCase();
}

export function ProviderIcon({
  id,
  label = id,
  size = "md",
  className,
}: {
  id: string;
  label?: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const brand = BRANDS[id.toLowerCase()];
  const color = brand?.color ?? NEUTRAL;
  const { box, glyph, text } = SIZES[size];
  const tile: React.CSSProperties = {
    backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)`,
    boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${color} 24%, transparent)`,
  };

  return (
    <div aria-hidden className={cn("flex shrink-0 items-center justify-center", box, className)} style={tile}>
      {brand?.image ? (
        <img src={brand.image} alt="" width={glyph} height={glyph} className="object-contain" draggable={false} />
      ) : brand?.glyph ? (
        <span
          style={{
            width: glyph,
            height: glyph,
            backgroundColor: color,
            maskImage: `url("${brand.glyph}")`,
            WebkitMaskImage: `url("${brand.glyph}")`,
            maskSize: "contain",
            WebkitMaskSize: "contain",
            maskRepeat: "no-repeat",
            WebkitMaskRepeat: "no-repeat",
            maskPosition: "center",
            WebkitMaskPosition: "center",
          }}
        />
      ) : (
        <span className={cn("font-mono font-semibold", text)} style={{ color }}>
          {initials(label)}
        </span>
      )}
    </div>
  );
}
