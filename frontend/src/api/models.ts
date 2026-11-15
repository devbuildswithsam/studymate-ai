// GET /api/models (backend: app/api/models.py). SMA-26.
import { useQuery } from '@tanstack/react-query'

import { apiGet } from '@/api/client'

export type ModelStatus = 'available' | 'rate_limited' | 'no_key'

/** Same fields as the backend's ModelInfo. */
export type ModelInfo = {
  id: string
  provider: string
  display_name: string
  supports_tools: boolean
  supports_json: boolean
  status: ModelStatus
}

export type ModelsResponse = {
  default_model: string | null
  models: ModelInfo[]
}

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => apiGet<ModelsResponse>('/api/models'),
  })
}
