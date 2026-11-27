import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import './index.css'
import { Layout, RouteError } from './pages/Layout'
import { Home } from './pages/Home'
import { JobPage } from './pages/JobPage'
import { Jobs } from './pages/Jobs'

// module level: a data router must not live in React state
const router = createBrowserRouter([
  {
    Component: Layout,
    ErrorBoundary: RouteError,
    children: [
      { index: true, Component: Home },
      { path: 'jobs', Component: Jobs },
      { path: 'jobs/:id', Component: JobPage },
    ],
  },
], { basename: import.meta.env.BASE_URL.replace(/\/$/, '') }) // served at /web/
const queryClient = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
