// Quizzes: make one from a document, and the list of mine with their best scores (SMA-63).
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

import { useDocuments } from '@/api/documents'
import { useCreateQuiz, useDeleteQuiz, useQuizzes } from '@/api/quizzes'
import { Button } from '@/components/ui/button'
import { friendlyError, generationError } from '@/lib/errors'

const COUNTS = [5, 10]

export function QuizzesPage() {
  return (
    <section className="max-w-3xl">
      <h1 className="text-2xl font-semibold">Quizzes</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Multiple-choice questions written by the AI from one of your documents, each with an
        explanation and the page it comes from.
      </p>
      <NewQuiz />
      <QuizList />
    </section>
  )
}

function NewQuiz() {
  const navigate = useNavigate()
  // "Make a quiz" on a document page arrives with that document already picked.
  const preselected = (useLocation().state as { documentId?: string } | null)?.documentId
  const documents = useDocuments()
  const create = useCreateQuiz()
  const ready = (documents.data ?? []).filter((d) => d.status === 'ready')
  const [picked, setPicked] = useState<string>()
  const [count, setCount] = useState(5)
  const documentId = picked ?? preselected ?? ready[0]?.id

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!documentId) return
    create.mutate(
      { document_id: documentId, questions: count },
      { onSuccess: (quiz) => navigate(`/quizzes/${quiz.id}`) },
    )
  }

  if (documents.isSuccess && ready.length === 0) {
    return (
      <p className="mt-6 rounded-md bg-muted px-3 py-2 text-sm">
        Upload a document on the{' '}
        <Link to="/documents" className="underline">
          Documents
        </Link>{' '}
        page first: quizzes are made from your documents.
      </p>
    )
  }
  return (
    <form onSubmit={submit} className="mt-6 flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-sm">
        Document
        <select
          value={documentId ?? ''}
          onChange={(event) => setPicked(event.target.value)}
          className="rounded-md border bg-background px-3 py-2"
        >
          {ready.map((d) => (
            <option key={d.id} value={d.id}>
              {d.filename}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Questions
        <select
          value={count}
          onChange={(event) => setCount(Number(event.target.value))}
          className="rounded-md border bg-background px-3 py-2"
        >
          {COUNTS.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" disabled={!documentId || create.isPending}>
        {create.isPending ? 'Writing your quiz…' : 'Make quiz'}
      </Button>
      {create.isError && (
        <p role="alert" className="w-full text-sm text-red-600">
          {generationError(create.error)}
        </p>
      )}
    </form>
  )
}

function QuizList() {
  const quizzes = useQuizzes()
  const remove = useDeleteQuiz()

  if (quizzes.error)
    return <p className="mt-6 text-sm text-red-600">{friendlyError(quizzes.error)}</p>
  if (!quizzes.data) return null
  if (quizzes.data.length === 0) {
    return <p className="mt-6 text-sm text-muted-foreground">No quizzes yet.</p>
  }
  return (
    <ul className="mt-6 flex flex-col divide-y rounded-md border">
      {quizzes.data.map((quiz) => (
        <li key={quiz.id} aria-label={quiz.title} className="flex items-center gap-3 p-3">
          <div className="min-w-0 flex-1">
            <Link to={`/quizzes/${quiz.id}`} className="font-medium hover:underline">
              {quiz.title}
            </Link>
            <p className="text-xs text-muted-foreground">
              {quiz.document_name} · {quiz.question_count} questions ·{' '}
              {quiz.best_score === null
                ? 'not taken yet'
                : `best ${quiz.best_score}/${quiz.question_count}, last ${quiz.last_score}/${quiz.question_count}`}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={remove.isPending}
            onClick={() => remove.mutate(quiz.id)}
          >
            Delete
          </Button>
        </li>
      ))}
    </ul>
  )
}
