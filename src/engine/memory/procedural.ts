import type { MemoryGraph, ProcedureUnit, EpisodeUnit } from './memory-graph'
import { embed, cosineSimilarity } from './embedding'

export interface ProceduralSearchResult {
  procedure: ProcedureUnit
  score: number
}

export class ProceduralLayer {
  constructor(private graph: MemoryGraph) {}

  async distill(name: string, description: string, pattern: string, sourceEpisodes: string[]): Promise<string> {
    const embedding = await embed(`${name}: ${description}`, 'passage')

    const episodes = sourceEpisodes
      .map(id => this.graph.getEpisode(id))
      .filter((e): e is EpisodeUnit => e !== undefined)

    const successCount = episodes.filter(e => e.outcome === 'success').length
    const successRate = episodes.length > 0 ? successCount / episodes.length : 0

    return this.graph.addProcedure({
      name,
      description,
      pattern,
      sourceEpisodes,
      usageCount: 0,
      successRate,
      maturityScore: this.calculatePEMS(0, successRate, episodes.length),
      embedding
    })
  }

  async search(query: string, k = 5): Promise<ProceduralSearchResult[]> {
    const queryEmbedding = await embed(query, 'query')
    const procedures = this.graph.getAllProcedures()

    const scored: ProceduralSearchResult[] = []
    for (const proc of procedures) {
      if (!proc.embedding) continue
      const score = cosineSimilarity(queryEmbedding, proc.embedding)
      scored.push({ procedure: proc, score })
    }

    scored.sort((a, b) => b.score - a.score)
    return scored.slice(0, k)
  }

  getMature(threshold = 0.5): ProcedureUnit[] {
    return this.graph.getAllProcedures().filter(p => p.maturityScore >= threshold)
  }

  getMostUsed(limit: number): ProcedureUnit[] {
    return this.graph.getAllProcedures()
      .sort((a, b) => b.usageCount - a.usageCount)
      .slice(0, limit)
  }

  calculatePEMS(usageCount: number, successRate: number, episodeCount: number): number {
    const usageScore = Math.min(usageCount / 10, 1)
    const stabilityScore = successRate
    const experienceScore = Math.min(episodeCount / 5, 1)
    return (usageScore * 0.3 + stabilityScore * 0.5 + experienceScore * 0.2)
  }
}
