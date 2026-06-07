import type { MemoryGraph, EpisodeUnit, StepRecord, EpisodeOutcome } from './memory-graph'
import { embed, cosineSimilarity } from './embedding'

export interface EpisodicSearchResult {
  episode: EpisodeUnit
  score: number
}

export class EpisodicLayer {
  constructor(private graph: MemoryGraph) {}

  async recordEpisode(
    runId: string,
    taskDescription: string,
    trajectory: StepRecord[],
    outcome: EpisodeOutcome,
    feedback: string
  ): Promise<string> {
    const embedding = await embed(taskDescription, 'passage')
    return this.graph.addEpisode({
      runId,
      taskDescription,
      trajectory,
      outcome,
      feedback,
      embedding
    })
  }

  async search(query: string, k = 5): Promise<EpisodicSearchResult[]> {
    const queryEmbedding = await embed(query, 'query')
    const episodes = this.graph.getAllEpisodes()

    const scored: EpisodicSearchResult[] = []
    for (const episode of episodes) {
      if (!episode.embedding) continue
      const score = cosineSimilarity(queryEmbedding, episode.embedding)
      scored.push({ episode, score })
    }

    scored.sort((a, b) => b.score - a.score)
    return scored.slice(0, k)
  }

  getSuccessful(): EpisodeUnit[] {
    return this.graph.getSuccessfulEpisodes()
  }

  getByRunId(runId: string): EpisodeUnit[] {
    return this.graph.getAllEpisodes().filter(e => e.runId === runId)
  }

  getRecent(limit: number): EpisodeUnit[] {
    return this.graph.getAllEpisodes()
      .sort((a, b) => b.createdAt - a.createdAt)
      .slice(0, limit)
  }
}
