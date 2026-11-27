# Web stack for `clients/web/`: versions, snippets, pitfalls

Research date: 2026-11-27.
Scope: the React site next to the Python API (`docs/PLAN.md` item 1, contract in `docs/API.md`).
Versions come from the npm registry (`npm view <pkg> version`) on that day.
The APIs come from the official docs, the changelogs, and the `.d.ts` files in each published tarball.

**How the snippets were checked.**
Every snippet below sits in a scratch Vite app scaffolded with `create-vite@9.4.0 --template react-ts`, with exactly the pins in the table below.
All of them pass `tsc -b` (TypeScript 7.0.2) and `vite build` (Node 22.23).
In `vite dev`, the MSW worker is served at `/mockServiceWorker.js` and the `/v1` proxy forwards to `:8000`.
They were **not** clicked through in a browser.
Each snippet is labelled *docs* (taken from the official docs, adapted), *composed* (written against the `.d.ts`), or both.

## TL;DR

- **Node ≥ 22.22 is required.** React Router 8 needs `node@22.22+` and MSW 3 needs `>=22.12.0` ([RR upgrade guide](https://reactrouter.com/upgrading/v7), msw `engines`).
  The dev laptop currently has **Node 18.20.8**: Vite 8 will not even start on it.
  Install Node 22 LTS (or 24) before Friday.
- **Several majors are newer than most memory or tutorials:** Vite 8 (Rolldown), TypeScript 7 (native Go compiler), React Router 8, TanStack Table 9, React Flow 13, **MSW 3** (not v2), ECharts 6.
  Don't copy a tutorial snippet without checking it against this file.
- **Charts: uPlot.** It is 21 kB gzip against 179 kB for a tree-shaken ECharts line chart (measured), it is the engine Grafana's time-series panel is built on, and it handles streaming better.
- **Arrows from side-panel text into the flow:** React Flow cannot connect an edge to a DOM element outside the flow.
  Draw a fixed SVG overlay from the span's `getBoundingClientRect()` to the handle's screen position (`useInternalNode` + `flowToScreenPosition`), and redraw on viewport change, scroll and resize (snippet in §React Flow).
- **Mock with the MSW 3 Vite plugin** (`msw/vite` + `virtual:msw`): no `public/mockServiceWorker.js` to keep in sync.

## Pinned versions

| package | pin | checked | source |
|---|---|---|---|
| vite | 8.4.0 | 2026-11-27 | [vite.dev/guide](https://vite.dev/guide/), [Vite 8 announcement](https://vite.dev/blog/announcing-vite8) |
| @vitejs/plugin-react | 6.3.0 | 2026-11-27 | [README](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react/README.md) |
| create-vite | 9.4.0 | 2026-11-27 | npm; `template-react-ts` ships TS 7, Vite 8, oxlint |
| react, react-dom | 19.3.1 | 2026-11-27 | npm |
| @types/react / @types/react-dom | 19.3.3 / 19.3.0 | 2026-11-27 | npm |
| typescript | 7.0.2 | 2026-11-27 | [Announcing TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/) |
| tailwindcss, @tailwindcss/vite | 4.3.5 | 2026-11-27 | [Tailwind + Vite](https://tailwindcss.com/docs/installation/using-vite), [v4.3 post](https://tailwindcss.com/blog/tailwindcss-v4-3) |
| react-router | 8.5.3 | 2026-11-27 | [reactrouter.com](https://reactrouter.com/), [modes](https://reactrouter.com/start/modes), [v7→v8](https://reactrouter.com/upgrading/v7) |
| @tanstack/react-query | 5.108.4 | 2026-11-27 | [quick start](https://tanstack.com/query/latest/docs/framework/react/quick-start) |
| @tanstack/react-query-devtools | 5.108.4 | 2026-11-27 | npm (docs page 404'd, optional) |
| @tanstack/react-table | 9.3.1 | 2026-11-27 | [React quick start](https://tanstack.com/table/latest/docs/framework/react/quick-start), [v8→v9](https://tanstack.com/table/latest/docs/framework/react/guide/migrating) |
| @tanstack/react-virtual | 3.14.28 | 2026-11-27 | [Virtualizer API](https://tanstack.com/virtual/latest/docs/api/virtualizer) |
| @xyflow/react | 13.0.3 | 2026-11-27 | [reactflow.dev/learn](https://reactflow.dev/learn), [migrate to v13](https://reactflow.dev/learn/troubleshooting/migrate-to-v13), [what's new](https://reactflow.dev/whats-new) |
| animejs | 4.5.0 | 2026-11-27 | [docs](https://animejs.com/documentation), [releases](https://github.com/juliangarnier/anime/releases) |
| uplot | 1.6.32 | 2026-11-27 | [README + docs](https://github.com/leeoniya/uPlot) (last publish 2025-03: stable, not dead) |
| echarts (not recommended) | 6.1.0 | 2026-11-27 | [import guide](https://echarts.apache.org/handbook/en/basics/import), [v6 features](https://echarts.apache.org/handbook/en/basics/release-note/v6-feature) |
| msw | 3.0.8 | 2026-11-27 | [Vite integration](https://mswjs.io/guides/integrations/vite), [2.x→3.x](https://mswjs.io/docs/migrations/2.x-to-3.x) |

Starter `package.json` (scaffold first, then install these; exact pins on purpose for the hackathon):

```json
{
  "type": "module",
  "engines": { "node": ">=22.22" },
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "oxlint",
    "preview": "vite preview"
  },
  "dependencies": {
    "@tanstack/react-query": "5.108.4",
    "@tanstack/react-table": "9.3.1",
    "@tanstack/react-virtual": "3.14.28",
    "@xyflow/react": "13.0.3",
    "animejs": "4.5.0",
    "react": "19.3.1",
    "react-dom": "19.3.1",
    "react-router": "8.5.3",
    "uplot": "1.6.32"
  },
  "devDependencies": {
    "@tailwindcss/vite": "4.3.5",
    "@types/node": "26.6.11",
    "@types/react": "19.3.3",
    "@types/react-dom": "19.3.0",
    "@vitejs/plugin-react": "6.3.0",
    "msw": "3.0.8",
    "oxlint": "1.95.0",
    "tailwindcss": "4.3.5",
    "typescript": "7.0.2",
    "vite": "8.4.0"
  }
}
```

```bash
npm create vite@9.4.0 clients/web -- --template react-ts --no-interactive
cd clients/web && npm i   # then pin the versions above
```

Bundle sizes from `vite build` of the scratch app (min / gzip, each library in its own lazy route chunk):

| chunk | min | gzip |
|---|---|---|
| base: react, react-dom, react-router, react-query, app | 342 kB | 107 kB |
| @xyflow/react ERD page | 250 kB (+16 kB CSS) | 86 kB |
| TanStack Table + Virtual grid | 72 kB | 22 kB |
| animejs (animate, timeline, svg, onScroll, scope) | 55 kB | 21 kB |
| uPlot | 52 kB (+1.6 kB CSS) | 23 kB |
| ECharts 6, tree-shaken (line, grid, tooltip, dataZoom, canvas) | 529 kB | 179 kB |

## Vite 8 + TypeScript 7 + React

Vite 8 bundles with **Rolldown** and uses Oxc in place of esbuild and Rollup ([migration](https://vite.dev/guide/migration)).
`@vitejs/plugin-react` 6 does React Refresh with Oxc, and Babel is no longer a dependency ([Vite 8 post](https://vite.dev/blog/announcing-vite8)).
TypeScript 7 is the native Go port, "10x faster", and its package **ships no compiler API** ([TS 7 post](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)).

`vite.config.ts` (*composed*; the plugin lines follow the Tailwind and MSW docs, and `server.proxy` was checked against Vite's `ProxyOptions` type):

```ts
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { msw } from 'msw/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss(), msw()],
  server: {
    // Real API during dev when mocks are off: `uv run uvicorn s2d.api.main:app --port 8000`
    proxy: {
      '/v1': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
```

`src/vite-env.d.ts` (*composed*; needed because TS 7's `types` defaults to `[]`):

```ts
/// <reference types="vite/client" />
/// <reference types="msw/vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_TOKEN?: string
  readonly VITE_MOCK?: string
}
```

Pitfalls:
- **TS 7 removed options** (now errors): `target: es5`, `moduleResolution: node`/`node10`/`classic`, `baseUrl`, `module: amd|umd|system|none`, `downlevelIteration`, `esModuleInterop: false` ([TS 7 post](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)).
  The new defaults are `strict: true`, `module: esnext` and **`types: []`**, so ambient types such as `vite/client` and `msw/vite/client` must be listed (the template sets `"types": ["vite/client"]` in `tsconfig.app.json`).
- **No compiler API in TS 7** means anything that `import`s `typescript` breaks, including typescript-eslint.
  The 9.4.0 template already uses **oxlint**, so keep that.
  If you need typescript-eslint, the TS blog's workaround is npm aliases (`"typescript": "npm:@typescript/typescript6@^6.0.2"`).
- Vite does not typecheck: the template's `build` runs `tsc -b && vite build`.
  `tsc -b` works in TS 7.
- `build.rollupOptions` is now `build.rolldownOptions`, and the `esbuild` option is now `oxc`.
  The default `build.target` is Chrome 111 / Firefox 114 / Safari 16.4, so top-level `await` in `main.tsx` is fine ([migration](https://vite.dev/guide/migration)).
- `resolve.tsconfigPaths` is opt-in, so path aliases from `tsconfig` do nothing unless you enable it ([Vite 8 post](https://vite.dev/blog/announcing-vite8)).
- Harmless build warning: `"use no memo"` module directive in `react-compiler-runtime` (pulled in by React Flow 13).
- In VS Code, the TS 7 language service is the `TypeScriptTeam.native-preview` extension until it ships inside VS Code.

## Tailwind CSS v4 (Vite plugin)

There is no `tailwind.config.js` and no PostCSS config: add the Vite plugin (above) and one CSS import ([docs](https://tailwindcss.com/docs/installation/using-vite)).
Theme tokens are CSS variables in `@theme` ([theme docs](https://tailwindcss.com/docs/theme)).

`src/index.css` (*docs*):

```css
@import "tailwindcss";

/* dark mode by class instead of prefers-color-scheme */
@custom-variant dark (&:where(.dark, .dark *));

@theme {
  --color-panel: oklch(0.21 0.01 260);
  --color-accent: oklch(0.72 0.16 150);
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
}
```

Pitfalls:
- `dark:` follows `prefers-color-scheme` by default.
  Use the `@custom-variant` line above to switch it to a class ([dark mode](https://tailwindcss.com/docs/dark-mode)).
- `@theme { --color-panel: … }` creates `bg-panel`, `text-panel`, `border-panel` and so on, and `var(--color-panel)` works in plain CSS and SVG `stroke`.
- New in 4.1–4.3, useful for a Grafana look: `scrollbar-thin`, `scrollbar-thumb-*`, `text-shadow-*`, `mask-*`, `@container-size` ([v4.1](https://tailwindcss.com/blog/tailwindcss-v4-1), [v4.3](https://tailwindcss.com/blog/tailwindcss-v4-3)).
- React Flow 13 puts its styles in the `xyflow` CSS layer, so Tailwind utilities on custom nodes win without `!important` ([migrate to v13](https://reactflow.dev/learn/troubleshooting/migrate-to-v13)).

## React Router 8 (data mode) + TanStack Query 5

React Router v7→v8 is billed as a non-breaking upgrade, but **`react-router-dom` is gone**.
Import DOM APIs (`RouterProvider`) from `react-router/dom` and everything else from `react-router` ([upgrade guide](https://reactrouter.com/upgrading/v7)).
For this SPA use **data mode** (`createBrowserRouter`), not framework mode (that one needs `@react-router/dev` and its Vite plugin) ([modes](https://reactrouter.com/start/modes)).

`src/main.tsx` (*docs* for the router and the Query provider, *composed* for the MSW gate and lazy routes):

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import './index.css'
import { Home, JobPage } from './pages'

const router = createBrowserRouter([
  { path: '/', Component: Home },
  { path: '/jobs/:id', Component: JobPage },
  // route-level code splitting: heavy libraries load only on the page that needs them
  { path: '/grid', lazy: async () => ({ Component: (await import('./components/DataGrid')).Demo }) },
  { path: '/erd', lazy: async () => ({ Component: (await import('./components/Erd')).Erd }) },
  { path: '/anime', lazy: async () => ({ Component: (await import('./components/Pipeline')).Pipeline }) },
  { path: '/uplot', lazy: async () => ({ Component: (await import('./components/TimeSeries')).Demo }) },
  { path: '/echarts', lazy: async () => ({ Component: (await import('./components/EChart')).Demo }) },
])
const queryClient = new QueryClient()

async function enableMocking() {
  // `VITE_MOCK=0 npm run dev` talks to the real API through server.proxy
  if (!import.meta.env.DEV || import.meta.env.VITE_MOCK === '0') return
  const { network } = await import('virtual:msw')
  const { handlers } = await import('./mocks/handlers')
  network.configure({ handlers, onUnhandledFrame: 'bypass' })
  await network.enable()
}

await enableMocking()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
```

`src/api.ts`: typed client for `docs/API.md`, with polling that stops on `done`/`error` (*composed*; `queryOptions` and `refetchInterval(query)` are from the [useQuery reference](https://tanstack.com/query/latest/docs/framework/react/reference/useQuery)):

```ts
import { queryOptions } from '@tanstack/react-query'

// Shapes from docs/API.md (GET /v1/jobs/{id}, POST /v1/jobs)
export type JobStatus = 'queued' | 'running' | 'done' | 'error'
export type Step =
  | { name: string; done: true; s: number; note: string }
  | { name: string; done: false; eta_s: number }
export type Job = {
  job_id: string
  status: JobStatus
  position: number
  step: string | null
  step_index: number
  steps_total: number
  progress: number
  elapsed_s: number
  eta_s: number
  steps: Step[]
  error: string | null
}
export type NewJob = {
  company: string
  story: string
  difficulty?: 'easy' | 'medium' | 'hard'
  seed?: number
  n_customers?: number
  dirt?: 'none' | 'low' | 'medium' | 'high'
}

const TOKEN = import.meta.env.VITE_API_TOKEN ?? 'dev-token'

export class ApiError extends Error {
  status: number
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown }
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }
  return (await res.json()) as T
}

export const createJob = (body: NewJob) =>
  api<{ job_id: string; status: JobStatus; position: number }>('/v1/jobs', {
    method: 'POST',
    body: JSON.stringify(body),
  })

// Poll every 2 s until done/error (API.md: "every 2 s is fine")
export const jobOptions = (id: string) =>
  queryOptions({
    queryKey: ['job', id],
    queryFn: () => api<Job>(`/v1/jobs/${id}`),
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s === 'done' || s === 'error' ? false : 2000
    },
  })
```

`src/pages.tsx`: form → progress bar (*composed*):

```tsx
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router'
import { createJob, jobOptions } from './api'

export function Home() {
  const navigate = useNavigate()
  const create = useMutation({
    mutationFn: createJob,
    onSuccess: ({ job_id }) => navigate(`/jobs/${job_id}`),
  })
  return (
    <form
      className="grid gap-2 p-4"
      onSubmit={(e) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        create.mutate({ company: String(f.get('company')), story: String(f.get('story')) })
      }}
    >
      <textarea name="company" className="rounded bg-panel p-2" />
      <textarea name="story" className="rounded bg-panel p-2" />
      <button disabled={create.isPending}>Vygenerovat</button>
      {create.error && <p className="text-red-400">{create.error.message}</p>}
    </form>
  )
}

export function JobPage() {
  const { id = '' } = useParams()
  const { data, error } = useQuery(jobOptions(id))
  if (error) return <p>{error.message}</p>
  if (!data) return <p>…</p>
  return (
    <div className="p-4">
      <div className="h-2 rounded bg-panel">
        <div className="h-2 rounded bg-accent" style={{ width: `${data.progress * 100}%` }} />
      </div>
      <p>
        {data.step ?? data.status} · zbývá {data.eta_s} s
      </p>
    </div>
  )
}
```

Pitfalls:
- "Data Routers should not be held in React state": create the router once at module level ([data install](https://reactrouter.com/start/data/installation)).
- Route `lazy` returning `{ Component }` gives per-page code splitting.
  That keeps React Flow (86 kB gz) and the charts out of the first load.
- `refetchInterval` as a function gets the `Query`, so read `query.state.data`, not `data` ([useQuery](https://tanstack.com/query/latest/docs/framework/react/reference/useQuery)).
  `refetchIntervalInBackground` is `false` by default, so polling pauses in a hidden tab, which is what we want.
- The API answers `409` on `/result` until the job is done.
  Fetch the result only when `status === 'done'` (`enabled: job.status === 'done'`); otherwise `useQuery` retries the 409 three times.
- Errors are `{"detail": string}`, but 422 has `detail` as a list ([docs/API.md](../API.md)).
  `ApiError` above stringifies the list, so map it to field errors if the form needs them.
- In production the site and API share an origin (nginx routes `/v1/` to the API), so relative `/v1/...` URLs work both in dev (proxy) and in prod.

## TanStack Table 9 + TanStack Virtual 3

Table 9 is a new major: `useReactTable` is now **`useTable`**, and every table declares its **`features`** with `tableFeatures({...})` ([React quick start](https://tanstack.com/table/latest/docs/framework/react/quick-start)).
Row models move into feature slots (`sortedRowModel: createSortedRowModel()`), `sortingFns` is now `sortFns`, and rendering goes through `<table.FlexRender header|cell />` ([migration](https://tanstack.com/table/latest/docs/framework/react/guide/migrating)).
Virtual is still v3 (`useVirtualizer`).

`DataGrid.tsx`: sortable grid over 100k rows, virtualized (*docs* for the v9 table and sorting, *composed* for the Virtual wiring; the official virtualized-rows example page 404'd):

```tsx
import { useMemo, useRef } from 'react'
import {
  createSortedRowModel,
  rowSortingFeature,
  sortFns,
  tableFeatures,
  useTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'

// Rows from GET /v1/jobs/{id}/tables/{name}: unknown columns, so build defs from the names
type Row = Record<string, string | number | null>

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns,
})

export function DataGrid({ rows, columnNames }: { rows: Row[]; columnNames: string[] }) {
  // columns/rows must be stable references (useMemo / query data), or the table recomputes every render
  const columns = useMemo<ColumnDef<typeof features, Row>[]>(
    () => columnNames.map((name) => ({ accessorKey: name, header: name })),
    [columnNames],
  )
  const table = useTable({ features, columns, data: rows })
  const { rows: tableRows } = table.getRowModel()

  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 28, // fixed row height: no measureElement needed
    overscan: 10,
    useFlushSync: false, // avoids the React 19 flushSync warning while scrolling
  })

  const template = `repeat(${columnNames.length}, minmax(8rem, 1fr))`
  return (
    <div ref={scrollRef} className="h-[480px] overflow-auto font-mono text-sm">
      {/* display:grid rows so absolutely positioned rows keep column widths */}
      <div className="sticky top-0 z-10 grid bg-panel" style={{ gridTemplateColumns: template }}>
        {table.getHeaderGroups()[0].headers.map((header) => (
          <div key={header.id} className="cursor-pointer px-2 py-1" onClick={header.column.getToggleSortingHandler()}>
            <table.FlexRender header={header} />
            {{ asc: ' ▲', desc: ' ▼' }[header.column.getIsSorted() as string] ?? null}
          </div>
        ))}
      </div>
      <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((vi) => {
          const row = tableRows[vi.index]
          return (
            <div
              key={row.id}
              className="absolute inset-x-0 grid"
              style={{ gridTemplateColumns: template, height: vi.size, transform: `translateY(${vi.start}px)` }}
            >
              {row.getAllCells().map((cell) => (
                <div key={cell.id} className="truncate px-2">
                  <table.FlexRender cell={cell} />
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const demoRows: Row[] = Array.from({ length: 100_000 }, (_, i) => ({ id: i, segment: i % 3 ? 'rodiny' : 'studenti', total: i * 1.5 }))
const demoColumns = ['id', 'segment', 'total']
export const Demo = () => <DataGrid rows={demoRows} columnNames={demoColumns} />
```

Pitfalls:
- `ColumnDef` takes **two** type params in v9: `ColumnDef<typeof features, Row>`, and `createColumnHelper<typeof features, Row>()` does too.
- `data` and `columns` need stable references (module scope, `useMemo`, or query data), or the table rebuilds every render ([quick start](https://tanstack.com/table/latest/docs/framework/react/quick-start)).
- Don't destructure row/cell methods (`const { getValue } = cell`): in v9 they are prototype methods, no longer per-object arrow functions ([migration](https://tanstack.com/table/latest/docs/framework/react/guide/migrating)).
- `stockFeatures` gives the v8 "everything on" behaviour if you don't want to list features.
- Virtual: a fixed row height (`estimateSize`) means no `measureElement`.
  For variable heights, pass `ref={virtualizer.measureElement}` and `data-index={vi.index}` on each row ([API](https://tanstack.com/virtual/latest/docs/api/virtualizer)).
- `<table>` rows can't be absolutely positioned and keep their column widths, so use `display: grid` divs with a shared `gridTemplateColumns`, as above.
- React 19 logs a `flushSync` warning while scrolling; `useFlushSync: false` silences it ([React adapter](https://tanstack.com/virtual/latest/docs/framework/react/react-virtual)).
- `GET /v1/jobs/{id}/tables/{name}` pages with `limit`/`offset`.
  For huge tables, fetch pages on scroll (`useInfiniteQuery`) and set `count` to the total, or just cap at what the API returns.

## React Flow 13 (`@xyflow/react`): ERD nodes, handles per column, arrows from the side panel

v13 breaking changes you will hit when copying v12 code ([migrate to v13](https://reactflow.dev/learn/troubleshooting/migrate-to-v13)):
- `applyNodeChanges` and `applyEdgeChanges` are removed: `onNodesChange` gets a `NodeChangeset`, and you call `changes.applyTo(nodes)` (or use `useNodesState`).
- `useStore` is removed: use `useNodesStore`, `useEdgesStore`, `useViewportStore` and similar, and `useStoreApi` is now `useReactFlowStoreApi`.
- The `colorMode` prop is removed: color mode is automatic and `forceColorMode` forces one; styles live in the `xyflow` CSS layer.
- `useHandleConnections` is now `useNodeConnections`, and the `Handle` type is now `HandleBounds`.
- `nodeClickDistance` is replaced by `nodeDragThreshold`, and `paneClickDistance` is now `paneDragThreshold`; `fitViewOptions.padding` without a unit is in pixels.
- The CSS import is `@xyflow/react/style.css` (the old `dist/style.css` path still works), and there is an optional `xy-theme.css`.

`Erd.tsx`: a table node with one target and one source handle per column, an FK edge between columns, and an arrow from a span in the side panel to a column (*docs* for the node, handles and edges; *composed* for the overlay, checked against the v13 `.d.ts`: `useInternalNode`, `internals.positionAbsolute`, `internals.handleBounds`, `flowToScreenPosition`, `useOnViewportChange`):

```tsx
import { useLayoutEffect, useState } from 'react'
import {
  ReactFlow,
  ReactFlowProvider,
  Handle,
  Position,
  useEdgesState,
  useNodesState,
  useInternalNode,
  useOnViewportChange,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/style.css'

// ---- ERD table node: one target + one source handle per column ----
type Column = { name: string; type: string; pk?: boolean }
type TableNode = Node<{ table: string; columns: Column[] }, 'table'>

function TableNodeView({ data }: NodeProps<TableNode>) {
  return (
    <div className="min-w-48 rounded border border-white/20 bg-panel text-xs">
      <div className="border-b border-white/20 px-2 py-1 font-bold">{data.table}</div>
      {data.columns.map((c) => (
        // position: relative so each Handle centres on its own row, not on the node
        <div key={c.name} className="relative flex justify-between gap-4 px-2 py-0.5">
          <Handle type="target" position={Position.Left} id={`${c.name}-in`} />
          <span>{c.pk ? '🔑 ' : ''}{c.name}</span>
          <span className="opacity-60">{c.type}</span>
          <Handle type="source" position={Position.Right} id={`${c.name}-out`} />
        </div>
      ))}
    </div>
  )
}
const nodeTypes = { table: TableNodeView } satisfies NodeTypes // module level: stable reference

const initialNodes: TableNode[] = [
  { id: 'customers', type: 'table', position: { x: 0, y: 0 },
    data: { table: 'customers', columns: [{ name: 'customer_id', type: 'int', pk: true }, { name: 'segment', type: 'text' }] } },
  { id: 'orders', type: 'table', position: { x: 320, y: 40 },
    data: { table: 'orders', columns: [{ name: 'order_id', type: 'int', pk: true }, { name: 'customer_id', type: 'int' }, { name: 'total', type: 'numeric' }] } },
]
const initialEdges: Edge[] = [
  { id: 'fk1', source: 'customers', sourceHandle: 'customer_id-out', target: 'orders', targetHandle: 'customer_id-in', type: 'smoothstep' },
]

// ---- Arrow from a DOM span outside the flow to a column handle inside it ----
// React Flow edges only connect handles of nodes, so draw an SVG overlay in screen space.
function SpanToHandleArrow({ from, nodeId, handleId }: { from: HTMLElement | null; nodeId: string; handleId: string }) {
  const node = useInternalNode<TableNode>(nodeId) // re-renders when the node moves or is measured
  const { flowToScreenPosition } = useReactFlow()
  const [, bump] = useState(0)
  useOnViewportChange({ onChange: () => bump((n) => n + 1) }) // pan/zoom
  useLayoutEffect(() => {
    const onMove = () => bump((n) => n + 1)
    window.addEventListener('resize', onMove)
    window.addEventListener('scroll', onMove, true) // side panel scroll (capture catches inner scrollers)
    return () => {
      window.removeEventListener('resize', onMove)
      window.removeEventListener('scroll', onMove, true)
    }
  }, [])

  const h = node?.internals.handleBounds?.target?.find((b) => b.id === handleId)
  if (!from || !node || !h) return null
  const a = from.getBoundingClientRect()
  const b = flowToScreenPosition({
    x: node.internals.positionAbsolute.x + h.x + h.width / 2,
    y: node.internals.positionAbsolute.y + h.y + h.height / 2,
  })
  const x1 = a.right, y1 = a.top + a.height / 2
  const d = `M${x1},${y1} C${x1 + 80},${y1} ${b.x - 80},${b.y} ${b.x},${b.y}`
  return (
    <svg className="pointer-events-none fixed inset-0 z-50 h-full w-full overflow-visible">
      <path d={d} fill="none" stroke="var(--color-accent)" strokeWidth={2} />
    </svg>
  )
}

function ErdInner() {
  const [nodes, , onNodesChange] = useNodesState(initialNodes)
  const [edges, , onEdgesChange] = useEdgesState(initialEdges)
  const [span, setSpan] = useState<HTMLSpanElement | null>(null) // callback ref: re-render once the span exists
  return (
    <div className="flex h-[600px]">
      <aside className="w-72 overflow-auto p-3 text-sm">
        Zákazníci ze segmentu <span ref={setSpan} className="text-accent">studenti</span> začali odcházet…
      </aside>
      <div className="flex-1">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} fitView />
      </div>
      <SpanToHandleArrow from={span} nodeId="orders" handleId="customer_id-in" />
    </div>
  )
}

// The overlay uses React Flow hooks, so it must sit inside the provider (outside <ReactFlow/> is fine)
export const Erd = () => (
  <ReactFlowProvider>
    <ErdInner />
  </ReactFlowProvider>
)
```

**Can an edge connect to a DOM element outside the flow?**
No.
Edges connect node handles only, and the docs have no API for outside elements.
The in-flow escape hatches are `ViewportPortal` (flow coordinates) and `EdgeLabelRenderer` (HTML labels) ([ViewportPortal](https://reactflow.dev/api-reference/components/viewport-portal)).
Hence the overlay recipe:
1. A `position: fixed` full-screen SVG with `pointer-events: none`, rendered inside `ReactFlowProvider` but outside `<ReactFlow>`.
2. Start point: `span.getBoundingClientRect()` (screen pixels).
3. End point: `useInternalNode(id)` → `internals.positionAbsolute + handleBounds.target[i].{x,y,width,height}` (flow coordinates) → `flowToScreenPosition` (screen pixels).
4. Redraw on `useOnViewportChange` (pan/zoom), node moves (`useInternalNode` re-renders), the panel's `scroll` (capture listener) and window `resize`.

The alternative is to make the side panel part of the flow, as a node pinned with `draggable: false` and real edges.
It is simpler to keep in sync, but the panel then pans and zooms with the canvas.
Pick the overlay if the panel must stay fixed.

Pitfalls:
- Define `nodeTypes` / `edgeTypes` at module level (or `useMemo`), or React Flow warns and remounts every node.
- The flow's parent needs an explicit width and height.
- Every handle needs a unique `id` when there are several of the same type, and edges refer to them with `sourceHandle` / `targetHandle` ([handles](https://reactflow.dev/learn/customization/handles)).
- Put `position: relative` on each row, or every per-column `Handle` centres on the whole node side.
- Hide handles with `opacity: 0` / `visibility: hidden`, never `display: none`, because they must be measurable.
- If columns are added or removed after mount, call `useUpdateNodeInternals()(nodeId)` ([docs](https://reactflow.dev/api-reference/hooks/use-update-node-internals)).
- Node `data` must be a `type`, not an `interface` (it has to be assignable to `Record<string, unknown>`) ([TypeScript guide](https://reactflow.dev/learn/advanced-use/typescript)).
- Use the `nodrag` class on inputs and buttons inside nodes.
- React Flow UI has a ready-made [Database Schema Node](https://reactflow.dev/ui/components/database-schema-node) (page not read).
  The node above is a dependency-free equivalent.

## anime.js 4

v4 is all named exports from `animejs` (there is no default `anime()` any more), and subpath imports (`animejs/animation`, `animejs/svg`, `animejs/events`, `animejs/scope` and others) exist since 4.2 ([module imports](https://animejs.com/documentation/getting-started/module-imports)).
In React, wrap everything in **`createScope({ root })`** and call **`scope.revert()`** in the effect cleanup ([React guide](https://animejs.com/documentation/getting-started/using-with-react)).

`Pipeline.tsx`: staggered steps, line drawing, a dot along the path, a scroll-triggered animation, and reduced motion (*docs* for each call, *composed* as a whole; signatures checked in the `.d.ts`):

```tsx
import { useEffect, useRef } from 'react'
import { animate, createScope, createTimeline, onScroll, stagger, svg, type Scope } from 'animejs'

// Five pipeline steps: boxes pop in, the connecting line draws, a dot travels along it.
export function Pipeline() {
  const root = useRef<HTMLDivElement>(null)
  const scope = useRef<Scope | null>(null)

  useEffect(() => {
    scope.current = createScope({
      root, // selectors below are scoped to this element
      mediaQueries: { reduceMotion: '(prefers-reduced-motion: reduce)' },
    }).add((self) => {
      const reduce = self?.matches.reduceMotion // the scope re-runs this when the query flips
      const d = (ms: number) => (reduce ? 0 : ms)

      createTimeline({ defaults: { ease: 'outExpo' } })
        .add('.step', { opacity: [0, 1], y: [12, 0], duration: d(500), delay: stagger(d(90)) })
        .add(svg.createDrawable('.wire'), { draw: ['0 0', '0 1'], duration: d(1200), ease: 'inOutQuad' }, '-=200')

      if (!reduce) {
        animate('.dot', { ...svg.createMotionPath('.wire'), duration: 3000, ease: 'linear', loop: true })
      }

      // play once when the chart section scrolls into view
      animate('.bar', {
        scaleY: [0, 1],
        duration: d(800),
        delay: stagger(d(40)),
        autoplay: onScroll({ target: '.bars', enter: 'bottom top' }),
      })
    })
    return () => scope.current?.revert() // removes animations, observers and inline styles (StrictMode-safe)
  }, [])

  return (
    <div ref={root}>
      <div className="flex gap-4">
        {['spec', 'simulace', 'dvojče', 'ověření', 'příběh'].map((s) => (
          <div key={s} className="step rounded bg-panel px-3 py-2">{s}</div>
        ))}
      </div>
      <svg viewBox="0 0 400 40" className="w-full">
        <path className="wire" d="M10 20 C100 0 300 40 390 20" fill="none" stroke="currentColor" />
        <circle className="dot" r="4" fill="var(--color-accent)" />
      </svg>
      <div className="bars flex h-32 items-end gap-1">
        {[3, 5, 2, 8, 6].map((h, i) => (
          <div key={i} className="bar w-4 origin-bottom bg-accent" style={{ height: `${h * 10}%` }} />
        ))}
      </div>
    </div>
  )
}
```

API notes (from the `.d.ts` and the docs):
- `animate(targets, params): JSAnimation`, and `createTimeline(params?).add(targets, params, position)`.
  The position can be ms, a label, `'<'` (with the previous one) or a relative `'-=200'` / `'<-=500'` ([timeline](https://animejs.com/documentation/timeline)).
- `stagger(value, { from, grid, axis, … })`; since 4.4 the callback's third argument is `targets`, not `total` ([releases](https://github.com/juliangarnier/anime/releases)).
- `svg.createDrawable(selector, start?, end?)` returns an **array** of proxies; animate `draw: ['0 0', '0 1']` (start/end fractions) ([createDrawable](https://animejs.com/documentation/svg/createdrawable)).
- `svg.createMotionPath(path, offset?)` returns `{ translateX, translateY, rotate }`; spread it into `animate` ([createMotionPath](https://animejs.com/documentation/svg/createmotionpath)).
- `onScroll({ target, container, enter, leave, sync, repeat, debug, axis, onEnter, onLeave, … })` goes in `autoplay`.
  `sync: true` scrubs with the scroll, and `debug: true` draws the thresholds ([onScroll](https://animejs.com/documentation/events/onscroll)).
- `createScope({ root, defaults, mediaQueries })` (`root` accepts a React ref); `self.matches.<name>` holds the media-query booleans, and the scope re-runs on change ([mediaQueries](https://animejs.com/documentation/scope/scope-parameters/mediaqueries)).

Pitfalls:
- **Reduced motion is not automatic.**
  The only documented pattern is the `mediaQueries` one above: set durations to 0 and skip looping animations.
- Always `revert()`: StrictMode runs effects twice in dev, and without `revert()` you get doubled animations and stuck inline styles.
  Since 4.4, `revert()` also restores object props and attributes.
- 4.4 changed transforms to a fixed order (perspective > translate > rotate > scale > skew), and `matrix`/`matrix3d` can no longer be animated.
- Easing names are plain strings like `'outExpo'`, `'inOutQuad'` and `'linear'`.
  Since 4.2 the `linear()`, `steps()`, `irregular()` and `cubicBezier()` *functions* are separate modules (`animejs/easings/linear` and so on in the exports map) ([releases](https://github.com/juliangarnier/anime/releases)).
- Selectors inside a scope only match under `root`, so the SVG must be inside the ref'd element.

## Charts: uPlot vs ECharts → **uPlot**

| | uPlot 1.6.32 | ECharts 6.1.0 |
|---|---|---|
| size, gzip | **21 kB** full lib ([bundlephobia](https://bundlephobia.com/package/uplot@1.6.32)); 23 kB in our build | 359 kB full ([bundlephobia](https://bundlephobia.com/package/echarts@6.1.0)); **179 kB** tree-shaken line + tooltip + dataZoom (our build) |
| speed | 166,650 points in 25 ms cold start; 3,600 points at 60 fps streaming at about 10 % CPU ([README](https://github.com/leeoniya/uPlot)) | same streaming bench: about 70 % CPU, 85 MB (ECharts 5, from uPlot's README) |
| time series | built for it: x axis is unix **seconds**, aligned columnar arrays | `xAxis.type: 'time'`, ms timestamps, `[t, v]` pairs or dataset |
| dark theme | none built in; colours set per axis/series (snippet) | built-in `'dark'`, `chart.setTheme()` in v6 ([v6 features](https://echarts.apache.org/handbook/en/basics/release-note/v6-feature)) |
| live updates | `u.setData(data)` | `setOption(opt, { lazyUpdate: true })`; `appendData` for over a million points |
| Grafana | Grafana's time-series panels render with uPlot ([grafana-ui uPlot components](https://github.com/grafana/grafana/tree/main/packages/grafana-ui/src/components/uPlot)) | — |
| extras | zoom by drag-select; no tick-label collision avoidance, no pan ([non-features](https://github.com/leeoniya/uPlot)) | everything: legends, tooltips, heatmaps, maps, animations |

**Recommendation: uPlot.**
The "Grafana look" is literally uPlot: thin lines, translucent fill, dark grid, crosshair cursor, legend with live values.
It is 8× smaller than even a trimmed ECharts, and our series (about 700 days × a few metrics) are tiny for it.
Pick ECharts only if someone needs a heatmap, a pie or a Sankey on Friday night.
Then lazy-load it on that page only (`echarts/core` + `use([...])`).

`TimeSeries.tsx`: Grafana-style dark panel with live data (*composed* from the uPlot docs; the option types were checked against `uPlot.d.ts`):

```tsx
import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

// Grafana-like dark time series. x = unix SECONDS (uPlot default), ascending.
const axis = { stroke: '#9fa7b3', grid: { stroke: '#2c3235', width: 1 }, ticks: { stroke: '#2c3235' } }

export function TimeSeries({ data, label }: { data: uPlot.AlignedData; label: string }) {
  const el = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)

  // create once
  useEffect(() => {
    const box = el.current!
    const opts: uPlot.Options = {
      width: box.clientWidth,
      height: 260, // required; plot area only, legend is extra
      series: [{}, { label, stroke: '#73bf69', width: 1.5, fill: 'rgba(115,191,105,0.12)' }],
      axes: [axis, axis],
      cursor: { drag: { x: true, y: false } }, // drag to zoom x
    }
    plot.current = new uPlot(opts, data, box)
    const ro = new ResizeObserver(() => plot.current?.setSize({ width: box.clientWidth, height: 260 }))
    ro.observe(box)
    return () => {
      ro.disconnect()
      plot.current?.destroy()
      plot.current = null
    }
  }, [label]) // `data` deliberately left out: updates go through setData below

  // live updates: replace data, keep the instance
  useEffect(() => {
    plot.current?.setData(data)
  }, [data])

  return <div ref={el} className="w-full bg-[#181b1f]" />
}

const t0 = 1_775_000_000
export const Demo = () => (
  <TimeSeries label="tržby" data={[Array.from({ length: 700 }, (_, i) => t0 + i * 86400), Array.from({ length: 700 }, (_, i) => 100 + Math.sin(i / 20) * 10)]} />
)
```

ECharts equivalent, for reference only (*docs* for the tree-shaken import):

```tsx
// Measured for size only (see doc): tree-shaken ECharts line chart.
import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

export function EChart({ points }: { points: [number, number][] }) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  useEffect(() => {
    chart.current = echarts.init(el.current!, 'dark')
    const ro = new ResizeObserver(() => chart.current?.resize())
    ro.observe(el.current!)
    return () => { ro.disconnect(); chart.current?.dispose() }
  }, [])
  useEffect(() => {
    chart.current?.setOption({
      xAxis: { type: 'time' }, yAxis: { type: 'value' }, tooltip: { trigger: 'axis' },
      dataZoom: [{ type: 'inside' }],
      series: [{ type: 'line', showSymbol: false, data: points }],
    }, { lazyUpdate: true })
  }, [points])
  return <div ref={el} style={{ height: 260 }} />
}

export const Demo = () => <EChart points={Array.from({ length: 700 }, (_, i) => [1_775_000_000_000 + i * 86_400_000, 100 + Math.sin(i / 20) * 10])} />
```

uPlot pitfalls:
- `width` and `height` are required and are the plot area only (the legend is extra), and there is no built-in resize, so use a `ResizeObserver` → `setSize` as above.
- x values are **seconds**, ascending and unique, with `null` for gaps.
  Data is aligned columns: `[xs, ys1, ys2…]` ([docs](https://github.com/leeoniya/uPlot/tree/master/docs)).
- After editing arrays in place, call `setData()`, not `redraw()`.
- Import `uplot/dist/uPlot.min.css`, or the legend and cursor render unstyled.
- Wrappers exist (`uplot-react` 1.2.4, [uplot-wrappers](https://github.com/skalinichev/uplot-wrappers)), but the 25-line `useEffect` above is all we need.

ECharts pitfalls: register `CanvasRenderer` yourself when tree-shaking ([import](https://echarts.apache.org/handbook/en/basics/import)).
v6 changed the default theme (legend at the bottom, new palette), and `echarts/theme/v5` brings the old one back ([v6 upgrade guide](https://echarts.apache.org/handbook/en/basics/release-note/v6-upgrade-guide)).

## MSW 3 (mocking `docs/API.md` in the browser)

**Current is MSW 3, not v2.**
These are the v2→v3 changes you'll hit ([2.x→3.x](https://mswjs.io/docs/migrations/2.x-to-3.x)):
- Imports moved off the root: `http`, `HttpResponse` from **`msw/http`**; `delay` from **`msw/utils/delay`**; `setupWorker` still from `msw/browser`.
- `onUnhandledRequest` is now **`onUnhandledFrame`**, and its callback gets `{ frame, defaults }`.
- `worker.stop()` returns a Promise, and starting an already started worker throws.
- MSW 3 is ESM-only, needs Node ≥ 22.12 and TypeScript ≥ 5.9, and GraphQL is link-first (`graphql.link(url)`).
- **New: the Vite plugin `msw/vite`**.
  It serves the worker itself, so no `npx msw init public/` is needed, and it does nothing in production builds ([Vite guide](https://mswjs.io/guides/integrations/vite)).

`src/mocks/handlers.ts`: fake job lifecycle matching `docs/API.md` (202 → running steps → done, 404, 409, 422) (*composed* on the documented `http`/`HttpResponse`/`delay` API):

```ts
import { http, HttpResponse } from 'msw/http'
import { delay } from 'msw/utils/delay'
import type { Job, NewJob } from '../api'

const STEPS = ['specifikace (AI)', 'kalibrace a simulace', 'dvojče bez příběhu', 'ověření', 'český příběh (AI)']
const started = new Map<string, number>() // job_id -> start ms
const TOTAL_S = 20 // a fake run lasts 20 s

function status(id: string): Job {
  const elapsed = Math.round((Date.now() - started.get(id)!) / 1000)
  const done = elapsed >= TOTAL_S
  const per = TOTAL_S / STEPS.length
  const idx = done ? STEPS.length : Math.floor(elapsed / per) + 1
  return {
    job_id: id,
    status: done ? 'done' : 'running',
    position: 0,
    step: done ? null : STEPS[idx - 1],
    step_index: idx,
    steps_total: STEPS.length,
    progress: done ? 1 : elapsed / TOTAL_S,
    elapsed_s: elapsed,
    eta_s: done ? 0 : TOTAL_S - elapsed,
    steps: STEPS.map((name, i) =>
      i < idx - (done ? 0 : 1)
        ? { name, done: true, s: per, note: '' }
        : { name, done: false, eta_s: per },
    ),
    error: null,
  }
}

export const handlers = [
  http.post<never, NewJob>('/v1/jobs', async ({ request }) => {
    const body = await request.json()
    if (!body.company || !body.story) {
      return HttpResponse.json(
        { detail: [{ type: 'value_error', loc: ['body'], msg: 'Value error, give company and story, or spec_yaml' }] },
        { status: 422 },
      )
    }
    const id = `20261127-${Date.now()}`
    started.set(id, Date.now())
    await delay(150)
    return HttpResponse.json({ job_id: id, status: 'queued', position: 0 }, { status: 202 })
  }),

  http.get<{ id: string }>('/v1/jobs/:id', ({ params }) => {
    if (!started.has(params.id)) return HttpResponse.json({ detail: 'job not found' }, { status: 404 })
    return HttpResponse.json(status(params.id))
  }),

  http.get<{ id: string }>('/v1/jobs/:id/result', ({ params }) => {
    if (!started.has(params.id)) return HttpResponse.json({ detail: 'job not found' }, { status: 404 })
    if (status(params.id).status !== 'done')
      return HttpResponse.json({ detail: 'job is running, not done' }, { status: 409 })
    return HttpResponse.json({ job_id: params.id, verification: [] })
  }),
]
```

The wiring is in `vite.config.ts` (`msw()`) and `main.tsx` (`virtual:msw`, `network.configure`, `await network.enable()` **before** `createRoot`) above.

Pitfalls:
- **The docs' "browser integration" page is stale** (it shows `process.env.NODE_ENV` and `ReactDOM.render`).
  Follow the Vite guide.
- Await `enable()` before rendering, or the first requests race the worker registration.
- `onUnhandledFrame: 'bypass'` keeps unmocked requests (fonts, HMR) quiet; `'warn'` is the default.
- Without the plugin (`mode: 'worker-only'` or another bundler) you need `npx msw init ./public --save`, which records `"msw": { "workerDirectory": "./public" }` in `package.json` so the worker is re-copied on every install.
  A stale v2 `mockServiceWorker.js` will not work with v3.
- Relative handler paths (`/v1/jobs`) match the page origin, which is what our relative `fetch('/v1/...')` uses.
  An absolute API host needs the full URL in `http.get`.
- Service workers need `localhost` or HTTPS.
  Opening the dev server by LAN IP over plain HTTP disables mocking.
- Mocks are dev-only.
  The offline replay demo at the venue uses the real API with `LLM_BACKEND=replay` (`docs/research/winning-plan.md`), not MSW.

## Not verified

- No snippet was run in a real browser (only `tsc -b`, `vite build`, and `vite dev` serving the worker and proxying `/v1`).
- The full verbatim code of the anime.js React guide was read only in summary, so the scope pattern above follows the `ScopeParams` types and the documented `revert()` cleanup.
- TanStack's official "virtualized rows" example for Table v9 returned 404, so the grid wiring is our own.
- ECharts `notMerge` vs `replaceMerge` semantics were not read beyond the `setOption` type comments.
