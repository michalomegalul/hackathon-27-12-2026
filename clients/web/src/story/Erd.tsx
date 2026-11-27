// ERD of the job's tables (React Flow 13): a node per table, a handle per column, an edge per
// foreign key from /tables (docs/research/web-stack.md, "React Flow 13").
import { createContext, use, useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/style.css'
import type { TableInfo } from '../api'
import { intCs } from '../format'
import { keyFks, layout } from './model'

// ---- table node: one target + one source handle per column -----------------------------

type TableData = { table: TableInfo; pk: string[]; fkCols: string[] }
type TableNode = Node<TableData, 'table'>

/** The column the active event moved: lit in its node. */
const ActiveColumn = createContext<{ table: string; column: string } | null>(null)

const handleCls = '!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-white/30'

function TableNodeView({ data }: NodeProps<TableNode>) {
  const active = use(ActiveColumn)
  const { table, pk, fkCols } = data
  return (
    <div className="min-w-56 overflow-hidden rounded-lg border border-line bg-panel font-mono text-[11px] text-slate-200 shadow-lg shadow-black/30">
      <div className="flex items-baseline justify-between gap-3 border-b border-line bg-white/5 px-2.5 py-1.5">
        <span className="text-xs font-semibold">{table.name}</span>
        <span className="text-[10px] tabular-nums text-muted">{intCs(table.rows)}</span>
      </div>
      {table.columns.map((c) => {
        const lit = active?.table === table.name && active.column === c.name
        return (
          // relative: each Handle centres on its own row, not on the node
          <div
            key={c.name}
            className={`relative flex h-[21px] items-center justify-between gap-4 px-2.5 transition-colors duration-300 ${
              lit ? 'bg-accent/20 text-accent' : ''
            }`}
          >
            <Handle type="target" position={Position.Left} id={`${c.name}-in`} isConnectable={false} className={handleCls} />
            <span className="truncate">
              {pk.includes(c.name) ? <span className="text-amber-300">◆ </span> : fkCols.includes(c.name) ? <span className="text-sky-300">◇ </span> : '  '}
              {c.name}
            </span>
            <span className={lit ? 'text-accent/80' : 'text-muted'}>{c.type.toLowerCase()}</span>
            <Handle type="source" position={Position.Right} id={`${c.name}-out`} isConnectable={false} className={handleCls} />
          </div>
        )
      })}
    </div>
  )
}
const nodeTypes = { table: TableNodeView } satisfies NodeTypes // module level: a stable reference

function buildGraph(tables: TableInfo[]): { nodes: TableNode[]; edges: Edge[] } {
  const fks = keyFks(tables)
  const pos = layout(tables, fks)
  const nodes: TableNode[] = tables.map((t) => ({
    id: t.name,
    type: 'table',
    position: pos.get(t.name) ?? { x: 0, y: 0 },
    data: { table: t, pk: t.primary_key ?? [], fkCols: fks.filter((f) => f.child === t.name).map((f) => f.column) },
  }))
  const edges: Edge[] = fks.map((f) => ({
    id: `${f.child}.${f.column}`,
    source: f.parent,
    sourceHandle: `${f.parentColumn}-out`,
    target: f.child,
    targetHandle: `${f.column}-in`,
    type: 'smoothstep',
    style: { stroke: 'oklch(0.55 0.02 260)', strokeWidth: 1.2 },
  }))
  return { nodes, edges }
}

// ---- the flow --------------------------------------------------------------------------

export function Erd({
  tables,
  active = null,
}: {
  tables: TableInfo[]
  /** the column to light (and the edges into its table) */
  active?: { table: string; column: string } | null
}) {
  const graph = useMemo(() => buildGraph(tables), [tables])
  const [nodes, , onNodesChange] = useNodesState(graph.nodes)
  const [edges, , onEdgesChange] = useEdgesState(graph.edges)
  // edges into the lit table stand out
  const shown = useMemo(
    () =>
      edges.map((e) =>
        active && (e.target === active.table || e.source === active.table)
          ? { ...e, animated: true, style: { ...e.style, stroke: 'var(--color-accent)', strokeOpacity: 0.7 } }
          : e,
      ),
    [edges, active],
  )
  return (
    <ActiveColumn value={active}>
      <div className="h-full w-full">
        <ReactFlow
          nodes={nodes}
          edges={shown}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodesConnectable={false}
          forceColorMode="dark"
          fitView
          fitViewOptions={{ padding: '6%' }}
          minZoom={0.2}
          zoomOnScroll={false} // the ERD sits in a long page: the wheel scrolls the page, +/- zoom
          preventScrolling={false}
        >
          <Background color="oklch(0.3 0.012 260)" gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </ActiveColumn>
  )
}
