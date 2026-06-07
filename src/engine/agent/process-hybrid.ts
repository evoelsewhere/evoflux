import type { AgentDefinition } from './agent-definition'
import type { TeamSharedState, TaskResult } from './team-state'
import { runSequential, type SequentialResult } from './process-sequential'
import { runHierarchical, type HierarchicalResult, type HierarchicalConfig } from './process-hierarchical'
import { AgentError } from '../errors'

export interface HybridStage {
  name: string
  process: 'sequential' | 'hierarchical'
  agents: string[]
  config?: Partial<HierarchicalConfig>
}

export interface HybridConfig {
  stages: HybridStage[]
  managerModel: string
  managerProvider: 'openai' | 'ollama'
  maxRounds: number
  maxStalls: number
}

export interface HybridResult {
  success: boolean
  output: string
  results: TaskResult[]
  stageResults: Array<{ stage: string; result: SequentialResult | HierarchicalResult }>
}

export async function runHybrid(
  allAgents: AgentDefinition[],
  state: TeamSharedState,
  config: HybridConfig,
  signal?: AbortSignal
): Promise<HybridResult> {
  const agentMap = new Map(allAgents.map(a => [a.id, a]))
  const allResults: TaskResult[] = []
  const stageResults: HybridResult['stageResults'] = []
  let lastOutput = ''

  for (const stage of config.stages) {
    if (signal?.aborted) throw new AgentError('Aborted')

    const stageAgents = stage.agents
      .map(id => agentMap.get(id))
      .filter((a): a is AgentDefinition => a !== undefined)

    if (stageAgents.length === 0) continue

    if (stage.process === 'sequential') {
      const result = await runSequential(stageAgents, state, signal)
      allResults.push(...result.results)
      stageResults.push({ stage: stage.name, result })
      lastOutput = result.output
    } else {
      const hierConfig: HierarchicalConfig = {
        managerModel: stage.config?.managerModel || config.managerModel,
        managerProvider: stage.config?.managerProvider || config.managerProvider,
        maxRounds: stage.config?.maxRounds || config.maxRounds,
        maxStalls: stage.config?.maxStalls || config.maxStalls,
        planning: stage.config?.planning || false
      }
      const result = await runHierarchical(stageAgents, state, hierConfig, signal)
      allResults.push(...result.results)
      stageResults.push({ stage: stage.name, result })
      lastOutput = result.output
    }
  }

  return {
    success: allResults.every(r => r.success),
    output: lastOutput,
    results: allResults,
    stageResults
  }
}
