import dagre from 'dagre'
import type { Node, Edge } from 'reactflow'

const NODE_WIDTH = 180
const NODE_HEIGHT = 60

export function autoLayout<T>(
  nodes: Node<T>[],
  edges: Edge[],
  direction: 'TB' | 'LR' = 'TB'
): Node<T>[] {
  const dagreGraph = new dagre.graphlib.Graph()
  dagreGraph.setDefaultEdgeLabel(() => ({}))

  dagreGraph.setGraph({
    rankdir: direction,
    nodesep: 60,
    ranksep: 80,
    edgesep: 30,
    marginx: 40,
    marginy: 40
  })

  for (const node of nodes) {
    dagreGraph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  }

  for (const edge of edges) {
    dagreGraph.setEdge(edge.source, edge.target)
  }

  dagre.layout(dagreGraph)

  return nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id)
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - NODE_WIDTH / 2,
        y: nodeWithPosition.y - NODE_HEIGHT / 2
      }
    }
  })
}
