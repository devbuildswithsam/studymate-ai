// Tasks (backend: app/api/tasks.py). SMA-40.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiGet, apiPatch, apiPost } from '@/api/client'

export type TaskStatus = 'todo' | 'doing' | 'done'
export type TaskPriority = 'low' | 'medium' | 'high'

/** Same fields as the backend's TaskOut. */
export type Task = {
  id: string
  title: string
  description: string | null
  due_date: string | null // "2026-11-20"
  priority: TaskPriority
  status: TaskStatus
  document_id: string | null
  created_by: 'user' | 'ai' // "ai": made by the AI through MCP (SMA-41)
  created_at: string
  completed_at: string | null
}

export type NewTask = { title: string; due_date?: string; priority: TaskPriority }
export type TaskChanges = Partial<
  Pick<Task, 'title' | 'description' | 'due_date' | 'priority' | 'status'>
>

const TASKS_KEY = ['tasks'] as const

export function useTasks() {
  return useQuery({ queryKey: TASKS_KEY, queryFn: () => apiGet<Task[]>('/api/tasks') })
}

/** After any change, reload the board (the server decides the order and completed_at). */
function useRefreshAfter<T, V>(mutationFn: (variables: V) => Promise<T>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TASKS_KEY }),
  })
}

export function useCreateTask() {
  return useRefreshAfter((task: NewTask) => apiPost<Task>('/api/tasks', task))
}

export function useUpdateTask() {
  return useRefreshAfter(({ id, changes }: { id: string; changes: TaskChanges }) =>
    apiPatch<Task>(`/api/tasks/${id}`, changes),
  )
}

export function useDeleteTask() {
  return useRefreshAfter((id: string) => apiDelete(`/api/tasks/${id}`))
}
