import { nanoid } from 'nanoid'

export type SemanticType = 'fact' | 'document' | 'code_snippet' | 'api_doc' | 'error_pattern'
export type EdgeType = 'ground' | 'distill' | 'refine' | 'inherit'
export type EpisodeOutcome = 'success' | 'failure'

export interface SemanticUnit {
  id: string
  type: SemanticType
  content: string
  embedding?: Float32Array
  metadata: Record<string, unknown>
  createdAt: number
  accessCount: number
}

export interface EpisodeUnit {
  id: string
  runId: string
  taskDescription: string
  trajectory: StepRecord[]
  outcome: EpisodeOutcome
  feedback: string
  embedding?: Float32Array
  createdAt: number
}

export interface StepRecord {
  step: number
  nodeId: string
  action: string
  observation: string
  timestamp: number
}

export interface ProcedureUnit {
  id: string
  name: string
  description: string
  pattern: string
  sourceEpisodes: string[]
  usageCount: number
  successRate: number
  maturityScore: number
  embedding?: Float32Array
  createdAt: number
  lastUsedAt: number
}

export interface MemoryEdge {
  id: string
  sourceId: string
  targetId: string
  type: EdgeType
  weight: number
  createdAt: number
}

export interface MemoryContext {
  semantic: SemanticUnit[]
  episodic: EpisodeUnit[]
  procedural: ProcedureUnit[]
  formatted: string
}

export class MemoryGraph {
  private semantic = new Map<string, SemanticUnit>()
  private episodic = new Map<string, EpisodeUnit>()
  private procedural = new Map<string, ProcedureUnit>()
  private edges: MemoryEdge[] = []

  // Semantic
  addSemantic(unit: Omit<SemanticUnit, 'id' | 'createdAt' | 'accessCount'>): string {
    const id = nanoid(10)
    this.semantic.set(id, { ...unit, id, createdAt: Date.now(), accessCount: 0 })
    return id
  }

  getSemantic(id: string): SemanticUnit | undefined {
    const unit = this.semantic.get(id)
    if (unit) unit.accessCount++
    return unit
  }

  getAllSemantic(): SemanticUnit[] {
    return Array.from(this.semantic.values())
  }

  removeSemantic(id: string): void {
    this.semantic.delete(id)
    this.edges = this.edges.filter(e => e.sourceId !== id && e.targetId !== id)
  }

  // Episodic
  addEpisode(unit: Omit<EpisodeUnit, 'id' | 'createdAt'>): string {
    const id = nanoid(10)
    this.episodic.set(id, { ...unit, id, createdAt: Date.now() })
    return id
  }

  getEpisode(id: string): EpisodeUnit | undefined {
    return this.episodic.get(id)
  }

  getAllEpisodes(): EpisodeUnit[] {
    return Array.from(this.episodic.values())
  }

  getSuccessfulEpisodes(): EpisodeUnit[] {
    return this.getAllEpisodes().filter(e => e.outcome === 'success')
  }

  // Procedural
  addProcedure(unit: Omit<ProcedureUnit, 'id' | 'createdAt' | 'lastUsedAt'>): string {
    const id = nanoid(10)
    this.procedural.set(id, { ...unit, id, createdAt: Date.now(), lastUsedAt: Date.now() })
    return id
  }

  getProcedure(id: string): ProcedureUnit | undefined {
    const proc = this.procedural.get(id)
    if (proc) {
      proc.usageCount++
      proc.lastUsedAt = Date.now()
    }
    return proc
  }

  getAllProcedures(): ProcedureUnit[] {
    return Array.from(this.procedural.values())
  }

  // Edges
  addEdge(sourceId: string, targetId: string, type: EdgeType, weight = 1.0): string {
    const id = nanoid(10)
    this.edges.push({ id, sourceId, targetId, type, weight, createdAt: Date.now() })
    return id
  }

  getEdgesFrom(sourceId: string): MemoryEdge[] {
    return this.edges.filter(e => e.sourceId === sourceId)
  }

  getEdgesTo(targetId: string): MemoryEdge[] {
    return this.edges.filter(e => e.targetId === targetId)
  }

  removeEdge(id: string): void {
    this.edges = this.edges.filter(e => e.id !== id)
  }

  // Stats
  getStats() {
    return {
      semanticCount: this.semantic.size,
      episodicCount: this.episodic.size,
      proceduralCount: this.procedural.size,
      edgeCount: this.edges.length
    }
  }

  // Serialization
  toJSON() {
    return {
      semantic: Array.from(this.semantic.values()).map(u => ({ ...u, embedding: undefined })),
      episodic: Array.from(this.episodic.values()).map(u => ({ ...u, embedding: undefined })),
      procedural: Array.from(this.procedural.values()).map(u => ({ ...u, embedding: undefined })),
      edges: this.edges
    }
  }
}
