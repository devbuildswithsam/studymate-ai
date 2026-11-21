// Progress: how my studying is going, at a glance (SMA-65).
// Read-only: four panels and a small chart of quiz scores. Every number is my own data.
import type { ReactNode } from 'react'

import { useProgress, type Progress, type QuizPoint } from '@/api/progress'
import { friendlyError } from '@/lib/errors'

export function ProgressPage() {
  const progress = useProgress()

  return (
    <section className="max-w-3xl">
      <h1 className="text-2xl font-semibold">Progress</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Your quizzes, flashcards, tasks and documents at a glance.
      </p>
      {progress.error && (
        <p role="alert" className="mt-6 text-sm text-red-600">
          {friendlyError(progress.error)}
        </p>
      )}
      {progress.data && <Panels data={progress.data} />}
    </section>
  )
}

function Panels({ data }: { data: Progress }) {
  const { quizzes, flashcards, tasks, documents } = data
  return (
    <>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <Panel title="Quizzes">
          {quizzes.average_percent === null ? (
            <Empty>No quiz taken yet. Make one on the Quizzes page.</Empty>
          ) : (
            <>
              <Big>{quizzes.average_percent}%</Big>
              <Small>average score · {plural(quizzes.attempts, 'attempt')}</Small>
            </>
          )}
        </Panel>
        <Panel title="Flashcards">
          {flashcards.decks === 0 ? (
            <Empty>No deck yet. Make one on the Flashcards page.</Empty>
          ) : (
            <>
              <Big>
                {flashcards.cards_known} of {flashcards.cards_reviewed}
              </Big>
              <Small>
                cards known (latest mark) · {plural(flashcards.decks, 'deck')} ·{' '}
                {plural(flashcards.reviews, 'review')}
              </Small>
            </>
          )}
        </Panel>
        <Panel title="Tasks">
          <Big>{tasks.done_last_7_days}</Big>
          <Small>
            done in the last 7 days · {tasks.open} open
            {tasks.overdue > 0 && (
              <span className="font-medium text-red-600"> · {tasks.overdue} overdue</span>
            )}
          </Small>
        </Panel>
        <Panel title="Documents">
          {documents.ready === 0 ? (
            <Empty>No document yet. Upload one on the Documents page.</Empty>
          ) : (
            <>
              <Big>
                {documents.studied} of {documents.ready}
              </Big>
              <Small>documents studied (in a study chat, a quiz or a deck)</Small>
            </>
          )}
        </Panel>
      </div>
      {quizzes.history.length > 0 && <QuizChart points={quizzes.history} />}
    </>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  const id = `panel-${title.toLowerCase()}`
  return (
    <section aria-labelledby={id} className="rounded-lg border p-4">
      <h2 id={id} className="text-sm font-medium text-muted-foreground">
        {title}
      </h2>
      <div className="mt-2">{children}</div>
    </section>
  )
}

const Big = ({ children }: { children: ReactNode }) => (
  <p className="text-3xl font-semibold">{children}</p>
)
const Small = ({ children }: { children: ReactNode }) => (
  <p className="mt-1 text-sm text-muted-foreground">{children}</p>
)
const Empty = ({ children }: { children: ReactNode }) => (
  <p className="text-sm text-muted-foreground">{children}</p>
)

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

const percent = (p: QuizPoint) => (p.total ? Math.round((100 * p.score) / p.total) : 0)

/** One bar per attempt, oldest on the left. One series, so no legend: the title names it. */
function QuizChart({ points }: { points: QuizPoint[] }) {
  return (
    <figure aria-labelledby="quiz-chart-title" className="mt-6 rounded-lg border p-4">
      <figcaption id="quiz-chart-title" className="text-sm font-medium text-muted-foreground">
        Quiz scores (latest {points.length})
      </figcaption>
      <div className="mt-3 flex h-32 items-end gap-0.5 border-b" aria-hidden="true">
        {points.map((p, i) => (
          <div
            key={i}
            data-testid="bar"
            title={`${p.quiz_title}: ${p.score}/${p.total} (${percent(p)}%)`}
            className="group relative flex h-full max-w-8 flex-1 items-end hover:bg-muted/50"
          >
            <div
              className="w-full rounded-t bg-primary"
              style={{ height: `${Math.max(percent(p), 2)}%` }}
            />
          </div>
        ))}
      </div>
      <p className="mt-1 flex justify-between text-xs text-muted-foreground">
        <span>oldest</span>
        <span>100% = all answers right</span>
        <span>newest</span>
      </p>
      {/* The same numbers as a table, for screen readers and anyone who prefers text. */}
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-muted-foreground">Show as a table</summary>
        <table className="mt-2 w-full text-left">
          <thead>
            <tr>
              <th className="font-medium">Date</th>
              <th className="font-medium">Quiz</th>
              <th className="font-medium">Score</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p, i) => (
              <tr key={i}>
                <td>{new Date(p.created_at).toLocaleDateString()}</td>
                <td>{p.quiz_title}</td>
                <td>
                  {p.score}/{p.total} ({percent(p)}%)
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}
