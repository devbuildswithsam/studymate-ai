// Progress dashboard numbers (backend: app/api/progress.py). SMA-65.
import { useQuery } from '@tanstack/react-query'

import { apiGet } from '@/api/client'

export type QuizPoint = { created_at: string; quiz_title: string; score: number; total: number }

export type Progress = {
  quizzes: { attempts: number; average_percent: number | null; history: QuizPoint[] }
  flashcards: { decks: number; cards_reviewed: number; cards_known: number; reviews: number }
  tasks: { done_last_7_days: number; open: number; overdue: number }
  documents: { ready: number; studied: number }
}

/** The browser's own date (not UTC): "overdue" must follow the student's calendar. */
export function progressUrl(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
  return `/api/progress?today=${today}`
}

export function useProgress() {
  const url = progressUrl()
  return useQuery({ queryKey: ['progress', url], queryFn: () => apiGet<Progress>(url) })
}
