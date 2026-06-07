import type { MemoryGraph, MemoryEdge } from './memory-graph'
import { SemanticLayer } from './semantic'
import { cosineSimilarity } from './embedding'

export interface RefinementResult {
  edgesAdded: number
  edgesRemoved: number
  contentReshaped: number
}

export class StageTwoRefinement {
  private semantic: SemanticLayer

  constructor(private graph: MemoryGraph) {
    this.semantic = new SemanticLayer(graph)
  }

  async refine(feedback: string): Promise<RefinementResult> {
    const result: RefinementResult = { edgesAdded: 0, edgesRemoved: 0, contentReshaped: 0 }

    const underConnection = await this.fixUnderConnection(feedback)
    result.edgesAdded = underConnection

    const overConnection = this.fixOverConnection()
    result.edgesRemoved = overConnection

    const reshaped = await this.reshapeContent(feedback)
    result.contentReshaped = reshaped

    return result
  }

  private async fixUnderConnection(feedback: string): Promise<number> {
    const searchResults = await this.semantic.search(feedback, 10)
    let added = 0

    for (let i = 0; i < searchResults.length; i++) {
      for (let j = i + 1; j < searchResults.length; j++) {
        const a = searchResults[i]
        const b = searchResults[j]

        if (a.score > 0.7 && b.score > 0.7) {
          const existingEdges = this.graph.getEdgesFrom(a.unit.id)
          const alreadyConnected = existingEdges.some(e => e.targetId === b.unit.id)

          if (!alreadyConnected) {
            this.graph.addEdge(a.unit.id, b.unit.id, 'refine', a.score)
            added++
          }
        }
      }
    }

    return added
  }

  private fixOverConnection(): number {
    const allEdges: MemoryEdge[] = []
    const semanticUnits = this.graph.getAllSemantic()

    for (const unit of semanticUnits) {
      allEdges.push(...this.graph.getEdgesFrom(unit.id))
    }

    let removed = 0
    for (const edge of allEdges) {
      if (edge.weight < 0.3) {
        this.graph.removeEdge(edge.id)
        removed++
      }
    }

    return removed
  }

  private async reshapeContent(feedback: string): Promise<number> {
    const feedbackWords = feedback.toLowerCase().split(/\s+/)
    const needsMoreDetail = feedbackWords.some(w => ['brief', 'short', 'missing', 'incomplete', 'more detail'].includes(w))
    const needsCompression = feedbackWords.some(w => ['verbose', 'long', 'redundant', 'too much', 'summarize'].includes(w))

    if (!needsMoreDetail && !needsCompression) return 0

    const units = this.graph.getAllSemantic()
    let reshaped = 0

    for (const unit of units) {
      if (needsMoreDetail && unit.content.length < 100) {
        unit.metadata['needsExpansion'] = true
        reshaped++
      }
      if (needsCompression && unit.content.length > 1000) {
        unit.metadata['needsCompression'] = true
        reshaped++
      }
    }

    return reshaped
  }
}
