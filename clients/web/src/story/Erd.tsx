// ERD of the job's tables (React Flow 13) and an SVG arrow from a span in the side panel to the
// KPI column an event moved. Recipe: docs/research/web-stack.md, "React Flow 13".
import { createContext, use, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useEdgesState,
  useInternalNode,
  useNodesState,
  useOnViewportChange,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/style.css'
import { animate, createScope, svg } from 'animejs'
import type { TableInfo } from '../api'
import { intCs } from '../format'
import { inferFks, layout, pkOf } from './model'

// ---- table node: one target + one source handle per column -----------------------------

type TableData = { table: TableInfo; pk?: string; fkCols: string[] }
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
              {c.name === pk ? <span className="text-amber-300">◆ </span> : fkCols.includes(c.name) ? <span className="text-sky-300">◇ </span> : '  '}
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
  const fks = inferFks(tables)
  const pos = layout(tables, fks)
  const nodes: TableNode[] = tables.map((t) => ({
    id: t.name,
    type: 'table',
    position: pos.get(t.name) ?? { x: 0, y: 0 },
    data: { table: t, pk: pkOf(t), fkCols: fks.filter((f) => f.child === t.name).map((f) => f.column) },
  }))
  const edges: Edge[] = fks.map((f) => ({
    id: `${f.child}.${f.column}`,
    source: f.parent,
    sourceHandle: `${f.column}-out`,
    target: f.child,
    targetHandle: `${f.column}-in`,
    type: 'smoothstep',
    style: { stroke: 'oklch(0.55 0.02 260)', strokeWidth: 1.2 },
  }))
  return { nodes, edges }
}

// ---- arrow from a DOM span outside the flow to a column inside it ----------------------

function visibleIn(r: DOMRect, box: DOMRect) {
  return r.bottom > box.top && r.top < box.bottom && r.right > box.left && r.left < box.right
}

/**
 * Fixed, full-screen SVG: start at the span (screen px), end at the column's target handle
 * (flow coordinates → screen px). Redrawn on pan/zoom, node moves, scroll and resize.
 * Drawn in with anime.js each time the target changes.
 */
export function SpanArrow({
  from,
  table,
  column,
  flowBox,
  reduce,
}: {
  from: HTMLElement | null
  table: string
  column: string
  flowBox: HTMLElement | null
  reduce: boolean
}) {
  const node = useInternalNode<TableNode>(table) // re-renders when the node moves or is measured
  const { flowToScreenPosition } = useReactFlow()
  const [, bump] = useState(0)
  useOnViewportChange({ onChange: () => bump((n) => n + 1) })
  useLayoutEffect(() => {
    const onMove = () => bump((n) => n + 1)
    window.addEventListener('resize', onMove)
    window.addEventListener('scroll', onMove, true) // capture: catches the side panel's own scroll
    return () => {
      window.removeEventListener('resize', onMove)
      window.removeEventListener('scroll', onMove, true)
    }
  }, [])

  const path = useRef<SVGPathElement>(null)
  const head = useRef<SVGCircleElement>(null)
  const ready = Boolean(from && node?.internals.handleBounds)
  // draw in when the target changes (and once the handle has been measured)
  useEffect(() => {
    if (!ready || !path.current) return
    const scope = createScope().add(() => {
      const ms = reduce ? 0 : 900
      animate(svg.createDrawable(path.current!), { draw: ['0 0', '0 1'], duration: ms, ease: 'inOutQuad' })
      if (head.current) animate(head.current, { opacity: [0, 1], scale: [0.2, 1], duration: ms / 3, delay: ms * 0.8, ease: 'outBack' })
    })
    return () => scope.revert()
  }, [ready, from, table, column, reduce])

  const h = node?.internals.handleBounds?.target?.find((b) => b.id === `${column}-in`)
  if (!from || !node || !h || !flowBox) return null
  const a = from.getBoundingClientRect()
  const panel = from.closest('[data-scroll]')?.getBoundingClientRect()
  const b = flowToScreenPosition({
    x: node.internals.positionAbsolute.x + h.x + h.width / 2,
    y: node.internals.positionAbsolute.y + h.y + h.height / 2,
  })
  const box = flowBox.getBoundingClientRect()
  const endVisible = b.x >= box.left && b.x <= box.right && b.y >= box.top && b.y <= box.bottom
  if ((panel && !visibleIn(a, panel)) || !endVisible) return null

  const x1 = a.right + 4, y1 = a.top + a.height / 2
  const dx = Math.max(60, (b.x - x1) * 0.45)
  const d = `M${x1},${y1} C${x1 + dx},${y1} ${b.x - dx},${b.y} ${b.x - 3},${b.y}`
  return (
    <svg className="pointer-events-none fixed inset-0 z-40 h-full w-full overflow-visible" aria-hidden>
      <defs>
        <filter id="arrow-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" />
        </filter>
      </defs>
      <circle cx={x1} cy={y1} r={3} fill="var(--color-accent)" />
      <path d={d} fill="none" stroke="var(--color-accent)" strokeOpacity={0.35} strokeWidth={6} filter="url(#arrow-glow)" />
      <path ref={path} d={d} fill="none" stroke="var(--color-accent)" strokeWidth={2} strokeLinecap="round" />
      <circle ref={head} cx={b.x - 3} cy={b.y} r={4.5} fill="var(--color-accent)" style={{ transformBox: 'fill-box', transformOrigin: 'center' }} />
    </svg>
  )
}

// ---- the flow --------------------------------------------------------------------------

/** Must sit inside a ReactFlowProvider (the arrow uses the same store). `children` = the overlay. */
export function Erd({
  tables,
  active,
  onBox,
  children,
}: {
  tables: TableInfo[]
  active: { table: string; column: string } | null
  onBox: (el: HTMLDivElement | null) => void
  children?: ReactNode
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
      <div ref={onBox} className="h-full w-full">
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
        >
          <Background color="oklch(0.3 0.012 260)" gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {children}
    </ActiveColumn>
  )
}
