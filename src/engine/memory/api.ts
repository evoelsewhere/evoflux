import type { MemoryGraph, MemoryContext, SemanticType, StepRecord, EpisodeOutcome } from './memory-graph'
import { MemoryGraph as MemoryGraphClass } from './memory-graph'
import { SemanticLayer } from './semantic'
import { EpisodicLayer } from './episodic'
import { ProceduralLayer } from './procedural'
import { StageOneConnection } from './stage1'
import { StageTwoRefinement, type RefinementResult } from './stage2'
import { StageThreeConsolidation, type ConsolidationResult } from './stage3'

export class WorkflowMemory {
  readonly graph: MemoryGraph
  readonly semantic: SemanticLayer
  readonly episodic: EpisodicLayer
  readonly procedural: ProceduralLayer
  private stage1: StageOneConnection
  private stage2: StageTwoRefinement
  private stage3: StageThreeConsolidation
  private currentRunId: string
  private currentTrajectory: StepRecord[] = []

  constructor(runId?: string) {
    this.graph = new MemoryGraphClass()
    this.semantic = new SemanticLayer(this.graph)
    this.episodic = new EpisodicLayer(this.graph)
    this.procedural = new ProceduralLayer(this.graph)
    this.stage1 = new StageOneConnection(this.graph)
    this.stage2 = new StageTwoRefinement(this.graph)
    this.stage3 = new StageThreeConsolidation(this.graph)
    this.currentRunId = runId || `run-${Date.now()}`
  }

  // Stage I: Get context for current step
  async getContext(observation: string, k = 5): Promise<MemoryContext> {
    return this.stage1.getContext(observation, k)
  }

  // Stage II: Refine based on feedback
  async refine(feedback: string): Promise<RefinementResult> {
    return this.stage2.refine(feedback)
  }

  // Stage III: Consolidate after run
  async consolidate(): Promise<ConsolidationResult> {
    return this.stage3.consolidate()
  }

  // Record a step in current trajectory
  recordStep(step: StepRecord): void {
    this.currentTrajectory.push(step)
  }

  // Record outcome of current run
  async recordOutcome(outcome: EpisodeOutcome, feedback: string): Promise<string> {
    return this.episodic.recordEpisode(
      this.currentRunId,
      this.currentTrajectory.map(s => s.action).join(' → '),
      this.currentTrajectory,
      outcome,
      feedback
    )
  }

  // Add semantic knowledge
  async addSemantic(content: string, type: SemanticType, metadata?: Record<string, unknown>): Promise<string> {
    return this.semantic.add(content, type, metadata)
  }

  // Search semantic memory
  async searchSemantic(query: string, k = 5) {
    return this.semantic.search(query, k)
  }

  // Search episodic memory
  async searchEpisodic(query: string, k = 5) {
    return this.episodic.search(query, k)
  }

  // Search procedural memory
  async searchProcedural(query: string, k = 5) {
    return this.procedural.search(query, k)
  }

  // Get stats
  getStats() {
    return this.graph.getStats()
  }

  // Serialize
  toJSON() {
    return this.graph.toJSON()
  }
}
