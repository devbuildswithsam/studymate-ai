import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import { AppRoutes } from '@/App'
import { makeQueryClient } from '@/lib/queryClient'

import './index.css'

// One cache for all API data (TanStack Query): loading, errors, retries and caching.
// SMA-59: any 401 makes it check whether the session has ended.
const queryClient = makeQueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
