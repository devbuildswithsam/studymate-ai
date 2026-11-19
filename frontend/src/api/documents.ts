// Documents (backend: app/api/documents.py). SMA-47.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiGet, apiPost } from '@/api/client'

/** Same fields as the backend's DocumentOut. */
export type DocumentInfo = {
  id: string
  filename: string
  mime_type: 'application/pdf' | 'text/plain' | 'text/markdown'
  size_bytes: number
  page_count: number | null // PDFs only
  status: 'processing' | 'ready' | 'failed'
  error: string | null // why it failed, e.g. "No text found: ..."
  summary: string | null // SMA-50
  key_points: string[] | null
  created_at: string
  can_retry: boolean // failed while embedding: POST .../retry can finish it
}

export const DOCUMENTS_KEY = ['documents'] as const

export function useDocuments() {
  return useQuery({
    queryKey: DOCUMENTS_KEY,
    queryFn: () => apiGet<DocumentInfo[]>('/api/documents'),
  })
}

/** After a change, reload the list (the server knows each document's status). */
function useRefreshAfter<T, V>(mutationFn: (variables: V) => Promise<T>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DOCUMENTS_KEY }),
  })
}

export function useRetryDocument() {
  return useRefreshAfter((id: string) => apiPost<DocumentInfo>(`/api/documents/${id}/retry`, {}))
}

export function useDeleteDocument() {
  return useRefreshAfter((id: string) => apiDelete(`/api/documents/${id}`))
}
