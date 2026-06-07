import type { MemoryGraph, EpisodeUnit, ProcedureUnit } from './memory-graph'
import { ProceduralLayer } from './procedural'

export interface ConsolidationResult {
  clustersFormed: number
  proceduresDistilled: number
  matureProcedures: number
}

export class StageThreeConsolidation {
  private procedural: ProceduralLayer

  constructor(private graph: MemoryGraph) {
    this.procedural = new ProceduralLayer(graph)
  }

  async consolidate(): Promise<ConsolidationResult> {
    const successfulEpisodes = this.graph.getSuccessfulEpisodes()
    if (successfulEpisodes.length < 2) {
      return { clustersFormed: 0, proceduresDistilled: 0, matureProcedures: 0 }
    }

    const clusters = this.clusterEpisodes(successfulEpisodes)

    let proceduresDistilled = 0
    for (const cluster of clusters) {
      if (cluster.length >= 2) {
        const pattern = this.extractPattern(cluster)
        if (pattern) {
          await this.procedural.distill(
            `Pattern from ${cluster.length} episodes`,
            pattern.summary,
            pattern.template,
            cluster.map(e => e.id)
          )
          proceduresDistilled++
        }
      }
    }

    const matureProcedures = this.procedural.getMature(0.5).length

    return {
      clustersFormed: clusters.length,
      proceduresDistilled,
      matureProcedures
    }
  }

  private clusterEpisodes(episodes: EpisodeUnit[]): EpisodeUnit[][] {
    const clusters: EpisodeUnit[][] = []
    const assigned = new Set<string>()

    for (const episode of episodes) {
      if (assigned.has(episode.id)) continue

      const cluster: EpisodeUnit[] = [episode]
      assigned.add(episode.id)

      for (const other of episodes) {
        if (assigned.has(other.id)) continue
        if (this.areSimilar(episode, other)) {
          cluster.push(other)
          assigned.add(other.id)
        }
      }

      clusters.push(cluster)
    }

    return clusters
  }

  private areSimilar(a: EpisodeUnit, b: EpisodeUnit): boolean {
    const aWords = new Set(a.taskDescription.toLowerCase().split(/\s+/))
    const bWords = new Set(b.taskDescription.toLowerCase().split(/\s+/))
    let overlap = 0
    for (const word of aWords) {
      if (bWords.has(word) && word.length > 3) overlap++
    }
    const minSize = Math.min(aWords.size, bWords.size)
    return minSize > 0 ? overlap / minSize > 0.3 : false
  }

  private extractPattern(cluster: EpisodeUnit[]): { summary: string; template: string } | null {
    if (cluster.length === 0) return null

    const commonSteps: string[] = []
    const minLength = Math.min(...cluster.map(e => e.trajectory.length))

    for (let i = 0; i < minLength; i++) {
      const actions = cluster.map(e => e.trajectory[i]?.action || '')
      const allSame = actions.every(a => a === actions[0])
      if (allSame && actions[0]) {
        commonSteps.push(actions[0])
      }
    }

    if (commonSteps.length === 0) return null

    return {
      summary: `Common pattern from ${cluster.length} successful runs`,
      template: commonSteps.join(' → ')
    }
  }
}
