export class WorkflowError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'WorkflowError'
  }
}

export class NodeExecutionError extends WorkflowError {
  readonly nodeId: string
  readonly nodeType: string

  constructor(nodeId: string, nodeType: string, message: string, options?: ErrorOptions) {
    super(`[${nodeType}:${nodeId}] ${message}`, options)
    this.name = 'NodeExecutionError'
    this.nodeId = nodeId
    this.nodeType = nodeType
  }
}

export class GraphError extends WorkflowError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'GraphError'
  }
}

export class CycleDetectedError extends GraphError {
  readonly cycle: string[]

  constructor(cycle: string[]) {
    super(`Cycle detected: ${cycle.join(' → ')}`)
    this.name = 'CycleDetectedError'
    this.cycle = cycle
  }
}

export class VariablePoolError extends WorkflowError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'VariablePoolError'
  }
}

export class TemplateError extends WorkflowError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'TemplateError'
  }
}

export class NodeFactoryError extends WorkflowError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'NodeFactoryError'
  }
}

export class ExecutionLimitError extends WorkflowError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'ExecutionLimitError'
  }
}

export class SandboxError extends WorkflowError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'SandboxError'
  }
}

export class MemoryError extends WorkflowError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'MemoryError'
  }
}

export class AgentError extends WorkflowError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'AgentError'
  }
}

export type Result<T, E = WorkflowError> =
  | { ok: true; value: T }
  | { ok: false; error: E }
