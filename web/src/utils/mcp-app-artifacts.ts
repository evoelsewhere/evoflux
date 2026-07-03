import type { ContentBlock } from '@/api/types'

type BlockWithMCPApp = ContentBlock & {
  extra?: {
    mcp_app?: {
      resourceUri?: unknown
    }
  } | null
}

export function mcpAppResourceUri(block: ContentBlock): string | null {
  const resourceUri = (block as BlockWithMCPApp).extra?.mcp_app?.resourceUri
  return typeof resourceUri === 'string' && resourceUri.length > 0 ? resourceUri : null
}

export function latestMCPAppResourceBlockIds(blocks: ContentBlock[]): Set<string> {
  const latestByResourceUri = new Map<string, string>()
  for (const block of blocks) {
    if (block.type !== 'tool' || !block.toolDone) continue
    const resourceUri = mcpAppResourceUri(block)
    if (resourceUri) latestByResourceUri.set(resourceUri, block.id)
  }
  return new Set(latestByResourceUri.values())
}
