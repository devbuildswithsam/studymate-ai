// GET /api/health (backend: app/api/health.py). SMA-24.
import { useQuery } from '@tanstack/react-query'

import { apiGet } from '@/api/client'

/** Same fields as the backend's HealthResponse. */
export type Health = {
  status: 'ok'
  version: string
  env: string
  auth_mode: string
}

export function useHealth() {
  return useQuery({
    queryKey: ['health'], // the cache key: every component using it shares one request
    queryFn: () => apiGet<Health>('/api/health'),
  })
}
