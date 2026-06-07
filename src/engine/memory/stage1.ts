import type { MemoryGraph, MemoryContext, SemanticUnit, EpisodeUnit, ProcedureUnit } from './memory-graph'
import { SemanticLayer } from './semantic'
import { EpisodicLayer } from './episodic'
import { ProceduralLayer } from './procedural'

export class StageOneConnection {
  private semantic: SemanticLayer
  private episodic: EpisodicLayer
  private procedural: ProceduralLayer

  constructor(private graph: MemoryGraph) {
    this.semantic = new SemanticLayer(graph)
    this.episodic = new EpisodicLayer(graph)
    this.procedural = new ProceduralLayer(graph)
  }

  async getContext(observation: string, k = 5): Promise<MemoryContext> {
    const [semanticResults, episodicResults, proceduralResults] = await Promise.all([
      this.semantic.search(observation, k),
      this.episodic.search(observation, k),
      this.procedural.search(observation, k)
    ])

    const semantic = semanticResults.map(r => r.unit)
    const episodic = episodicResults.map(r => r.episode)
    const procedural = proceduralResults.map(r => r.procedure)

    const parts: string[] = []

    if (semantic.length > 0) {
      parts.push('## Relevant Knowledge')
      for (const unit of semantic) {
        parts.push(`- [${unit.type}] ${unit.content}`)
      }
    }

    if (episodic.length > 0) {
      parts.push('## Similar Past Experiences')
      for (const ep of episodic) {
        const outcome = ep.outcome === 'success' ? '✓' : '✗'
        parts.push(`- ${outcome} ${ep.taskDescription.substring(0, 200)}`)
        if (ep.feedback) parts.push(`  Feedback: ${ep.feedback.substring(0, 200)}`)
      }
    }

    if (procedural.length > 0) {
      parts.push('## Known Patterns')
      for (const proc of procedural) {
        parts.push(`- ${proc.name}: ${proc.description}`)
        parts.push(`  Pattern: ${proc.pattern.substring(0, 300)}`)
      }
    }

    return {
      semantic,
      episodic,
      procedural,
      formatted: parts.join('\n')
    }
  }

  getLayers() {
    return {
      semantic: this.semantic,
      episodic: this.episodic,
      procedural: this.procedural
    }
  }
}
