import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, redirect } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import './index.css'
import { Layout, RouteError } from './pages/Layout'
import { Story } from './pages/Story'
import { History, HistoryRun } from './pages/History'
import { Rev } from './pages/Rev'
import { About } from './pages/About'
import { retryTransient } from './api'

const id = (p: { id?: string }) => encodeURIComponent(p.id ?? '')

// module level: a data router must not live in React state
const router = createBrowserRouter([
  {
    Component: Layout,
    ErrorBoundary: RouteError,
    children: [
      { index: true, Component: Story },
      { path: 'run/:id', Component: Story },
      // lazy: TanStack Table + Virtual load only with the data browser
      { path: 'run/:id/data', lazy: async () => ({ Component: (await import('./pages/DataPage')).DataPage }) },
      { path: 'rev', Component: Rev },
      { path: 'history', Component: History },
      { path: 'history/:id', Component: HistoryRun },
      { path: 'about', Component: About },
      // the v1 links (shared, bookmarked) open the new views
      { path: 'jobs', loader: () => redirect('/history') },
      { path: 'jobs/:id', loader: ({ params }) => redirect(`/run/${id(params)}`) },
      { path: 'jobs/:id/data', loader: ({ params }) => redirect(`/run/${id(params)}/data`) },
      { path: 'jobs/:id/story', loader: ({ params }) => redirect(`/run/${id(params)}#s-summary`) },
    ],
  },
], { basename: import.meta.env.BASE_URL.replace(/\/$/, '') }) // served at /web/
const queryClient = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: retryTransient } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
