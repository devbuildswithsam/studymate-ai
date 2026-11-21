// Quizzes (backend: app/api/quizzes.py). SMA-63.
// A quiz arrives WITHOUT its answers: they come back only in an attempt's results.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiGet, apiPost } from '@/api/client'

export type QuizQuestion = { question: string; options: string[]; page: number | null }

export type Quiz = {
  id: string
  title: string
  document_id: string | null // null once the document was deleted
  document_name: string
  created_at: string
  questions: QuizQuestion[]
}

export type QuizSummary = {
  id: string
  title: string
  document_id: string | null
  document_name: string
  created_at: string
  question_count: number
  attempts: number
  best_score: number | null // null: not taken yet
  last_score: number | null
}

export type QuestionResult = {
  chosen: number | null
  correct_answer: number
  is_correct: boolean
  explanation: string
  page: number | null
}

export type AttemptResult = { id: string; score: number; total: number; results: QuestionResult[] }

const QUIZZES_KEY = ['quizzes'] as const

export function useQuizzes() {
  return useQuery({ queryKey: QUIZZES_KEY, queryFn: () => apiGet<QuizSummary[]>('/api/quizzes') })
}

export function useQuiz(id: string) {
  return useQuery({
    queryKey: [...QUIZZES_KEY, id],
    queryFn: () => apiGet<Quiz>(`/api/quizzes/${id}`),
  })
}

export function useCreateQuiz() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { document_id: string; questions: number }) =>
      apiPost<Quiz>('/api/quizzes', body),
    onSuccess: (quiz) => {
      queryClient.setQueryData([...QUIZZES_KEY, quiz.id], quiz) // opens at once, no refetch
      return queryClient.invalidateQueries({ queryKey: QUIZZES_KEY, exact: true })
    },
  })
}

export function useSubmitAttempt(quizId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (answers: (number | null)[]) =>
      apiPost<AttemptResult>(`/api/quizzes/${quizId}/attempts`, { answers }),
    // The list's best and last scores changed.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUIZZES_KEY, exact: true }),
  })
}

export function useDeleteQuiz() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/quizzes/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUIZZES_KEY, exact: true }),
  })
}
