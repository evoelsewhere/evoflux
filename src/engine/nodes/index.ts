import { NodeFactory, type BaseNode } from '../node-factory'

import { StartNode } from './start'
import { EndNode } from './end'
import { LLMNode } from './llm'
import { CodeNode } from './code'
import { ConditionNode } from './condition'
import { HTTPRequestNode } from './http-request'
import { TemplateNode } from './template'
import { IterationNode } from './iteration'
import { LoopNode } from './loop'
import { VariableAggregatorNode } from './variable-aggregator'
import { VariableAssignerNode } from './variable-assigner'
import { KnowledgeRetrievalNode } from './knowledge-retrieval'
import { ParameterExtractorNode } from './parameter-extractor'
import { QuestionClassifierNode } from './question-classifier'
import { FileExplorerNode } from './file-explorer'
import { FileReaderNode } from './file-reader'
import { ContextLoaderNode } from './context-loader'
import { AgentOrchestratorNode } from './agent-orchestrator'
import { ShellNode } from './shell'
import { ManualTriggerNode, WebhookTriggerNode, ScheduleTriggerNode } from './triggers'
import { FileWriteNode } from './file-write'
import { SubWorkflowNode } from './sub-workflow'
import { WebSearchNode } from './web-search'
import { TextSplitterNode } from './text-splitter'
import { TextTransformNode } from './text-transform'
import { DelayNode } from './delay'
import { DataTransformNode } from './data-transform'
import { GotoNode } from './goto'
import { RetryNode } from './retry'
import { RouterNode } from './router'
import { AIAgentNode } from './ai-agent'
import { GitOpsNode } from './git-operations'

const registry = new Map<string, new () => BaseNode>([
  ['start', StartNode as unknown as new () => BaseNode],
  ['end', EndNode as unknown as new () => BaseNode],
  ['llm', LLMNode as unknown as new () => BaseNode],
  ['code', CodeNode as unknown as new () => BaseNode],
  ['condition', ConditionNode as unknown as new () => BaseNode],
  ['http-request', HTTPRequestNode as unknown as new () => BaseNode],
  ['template', TemplateNode as unknown as new () => BaseNode],
  ['iteration', IterationNode as unknown as new () => BaseNode],
  ['loop', LoopNode as unknown as new () => BaseNode],
  ['variable-aggregator', VariableAggregatorNode as unknown as new () => BaseNode],
  ['variable-assigner', VariableAssignerNode as unknown as new () => BaseNode],
  ['knowledge-retrieval', KnowledgeRetrievalNode as unknown as new () => BaseNode],
  ['parameter-extractor', ParameterExtractorNode as unknown as new () => BaseNode],
  ['question-classifier', QuestionClassifierNode as unknown as new () => BaseNode],
  ['file-explorer', FileExplorerNode as unknown as new () => BaseNode],
  ['file-reader', FileReaderNode as unknown as new () => BaseNode],
  ['context-loader', ContextLoaderNode as unknown as new () => BaseNode],
  ['agent-orchestrator', AgentOrchestratorNode as unknown as new () => BaseNode],
  ['shell', ShellNode as unknown as new () => BaseNode],
  ['manual-trigger', ManualTriggerNode as unknown as new () => BaseNode],
  ['webhook-trigger', WebhookTriggerNode as unknown as new () => BaseNode],
  ['schedule-trigger', ScheduleTriggerNode as unknown as new () => BaseNode],
  ['file-write', FileWriteNode as unknown as new () => BaseNode],
  ['sub-workflow', SubWorkflowNode as unknown as new () => BaseNode],
  ['web-search', WebSearchNode as unknown as new () => BaseNode],
  ['text-splitter', TextSplitterNode as unknown as new () => BaseNode],
  ['text-transform', TextTransformNode as unknown as new () => BaseNode],
  ['delay', DelayNode as unknown as new () => BaseNode],
  ['data-transform', DataTransformNode as unknown as new () => BaseNode],
  ['goto', GotoNode as unknown as new () => BaseNode],
  ['retry', RetryNode as unknown as new () => BaseNode],
  ['router', RouterNode as unknown as new () => BaseNode],
  ['ai-agent', AIAgentNode as unknown as new () => BaseNode],
  ['git-operations', GitOpsNode as unknown as new () => BaseNode]
])

const originalCreate = NodeFactory.create
;(NodeFactory as unknown as { create: (type: string) => BaseNode }).create = (type: string) => {
  const cls = registry.get(type)
  if (cls) return new cls()
  return originalCreate(type)
}

const originalHas = NodeFactory.has
;(NodeFactory as unknown as { has: (type: string) => boolean }).has = (type: string) => {
  return registry.has(type) || originalHas(type)
}

const originalGetRegisteredTypes = NodeFactory.getRegisteredTypes
;(NodeFactory as unknown as { getRegisteredTypes: () => string[] }).getRegisteredTypes = () => {
  return [...new Set([...originalGetRegisteredTypes(), ...registry.keys()])]
}
