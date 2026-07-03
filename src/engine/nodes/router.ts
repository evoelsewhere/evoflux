import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface Route {
  condition: string
  output_handle: string
}

interface RouterConfig {
  routes?: Route[]
  default_handle?: string
}

export class RouterNode extends BaseNode<RouterConfig> {
  readonly type = 'router'

  getMetadata(): NodeMetadata {
    return {
      type: 'router',
      label: 'Router',
      icon: 'branches',
      category: 'logic',
      description: 'Multi-way conditional routing. Evaluates conditions and activates the matching output edge.',
      inputs: [
        { name: 'input', label: 'Input', type: 'string', required: true }
      ],
      outputs: [
        { name: 'route_1', label: 'Route 1', type: 'string', required: false },
        { name: 'route_2', label: 'Route 2', type: 'string', required: false },
        { name: 'route_3', label: 'Route 3', type: 'string', required: false },
        { name: 'default', label: 'Default', type: 'string', required: false },
        { name: 'matched_route', label: 'Matched Route', type: 'string', required: false }
      ],
      defaultConfig: { routes: [], default_handle: 'default' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as RouterConfig
    const routes = cfg.routes || []
    const input = inputs.input

    for (const route of routes) {
      if (!route.condition) continue

      try {
        const fn = new Function('input', 'value', `return ${route.condition}`)
        const result = Boolean(fn(input, input))
        if (result) {
          return {
            [route.output_handle]: String(input),
            matched_route: route.output_handle,
            ...Object.fromEntries(routes.map(r => [r.output_handle, r.output_handle === route.output_handle ? String(input) : '']))
          }
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Expression evaluation failed'
        throw new NodeExecutionError(context.nodeId, this.type, `Invalid condition in route '${route.output_handle}': ${message}`, { cause: error })
      }
    }

    const defaultHandle = cfg.default_handle || 'default'
    return {
      [defaultHandle]: String(input),
      matched_route: defaultHandle,
      ...Object.fromEntries(routes.map(r => [r.output_handle, '']))
    }
  }
}
