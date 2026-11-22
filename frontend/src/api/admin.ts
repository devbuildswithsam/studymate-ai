// Admin usage (backend: app/api/admin.py). SMA-68.
import { useQuery } from '@tanstack/react-query'

import { apiGet } from '@/api/client'

export type UsageRow = {
  day: string // YYYY-MM-DD, UTC
  provider: string
  model: string
  calls: number
  failures: number
  tokens_in: number
  tokens_out: number
}

export type Usage = {
  days: number
  rows: UsageRow[] // newest day first, then by model
  totals: { calls: number; failures: number; tokens_in: number; tokens_out: number }
}

export function useUsage(days = 30) {
  return useQuery({
    queryKey: ['admin-usage', days],
    queryFn: () => apiGet<Usage>(`/api/admin/usage?days=${days}`),
    retry: false, // a 403 won't change by asking again
  })
}
