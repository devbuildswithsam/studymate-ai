// Taking one quiz: answer, check, see the score and why (SMA-63).
// The quiz arrives without its answers; the server scores the attempt and only then
// sends back the right answers and explanations.
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { type AttemptResult, type QuizQuestion, useQuiz, useSubmitAttempt } from '@/api/quizzes'
import { Button } from '@/components/ui/button'
import { friendlyError } from '@/lib/errors'
import { cn } from '@/lib/utils'

export function QuizPage() {
  const { quizId = '' } = useParams()
  const quiz = useQuiz(quizId)
  const submit = useSubmitAttempt(quizId)
  const [answers, setAnswers] = useState<(number | null)[]>([])
  const [result, setResult] = useState<AttemptResult | null>(null)

  if (quiz.isLoading) return <p className="text-muted-foreground">Loading quiz…</p>
  if (quiz.error || !quiz.data) {
    return (
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold">Quiz</h1>
        <p className="text-muted-foreground">{friendlyError(quiz.error)}</p>
        <Link to="/quizzes" className="text-sm underline">
          Back to quizzes
        </Link>
      </section>
    )
  }

  const { questions } = quiz.data
  const allAnswered = questions.every((_, i) => answers[i] !== undefined && answers[i] !== null)

  function choose(question: number, option: number) {
    if (result) return // checked: answers are locked until "Try again"
    const next = [...answers]
    next[question] = option
    setAnswers(next)
  }

  function check() {
    submit.mutate(
      questions.map((_, i) => answers[i] ?? null),
      { onSuccess: setResult },
    )
  }

  function tryAgain() {
    setAnswers([])
    setResult(null)
  }

  return (
    <section className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">{quiz.data.title}</h1>
        <p className="text-sm text-muted-foreground">
          From {quiz.data.document_name} · {questions.length} questions ·{' '}
          <Link to="/quizzes" className="underline">
            all quizzes
          </Link>
        </p>
      </header>

      {result && (
        <p role="status" className="rounded-md bg-muted px-4 py-3 text-lg font-semibold">
          Score: {result.score} / {result.total}
        </p>
      )}

      <ol className="space-y-6">
        {questions.map((question, index) => (
          <li key={index}>
            <QuestionCard
              number={index + 1}
              question={question}
              chosen={answers[index] ?? null}
              onChoose={(option) => choose(index, option)}
              result={result?.results[index]}
            />
          </li>
        ))}
      </ol>

      <div className="flex items-center gap-3">
        {result ? (
          <Button onClick={tryAgain}>Try again</Button>
        ) : (
          <Button onClick={check} disabled={!allAnswered || submit.isPending}>
            Check answers
          </Button>
        )}
        {submit.isError && (
          <p role="alert" className="text-sm text-red-600">
            {friendlyError(submit.error)}
          </p>
        )}
      </div>
    </section>
  )
}

type CardProps = {
  number: number
  question: QuizQuestion
  chosen: number | null
  onChoose: (option: number) => void
  result?: AttemptResult['results'][number]
}

function QuestionCard({ number, question, chosen, onChoose, result }: CardProps) {
  return (
    // fieldset + legend: the options are one group, named by the question.
    <fieldset className="rounded-md border p-4">
      <legend className="px-1 font-medium">
        {number}. {question.question}
      </legend>
      <div className="mt-2 flex flex-col gap-2">
        {question.options.map((option, i) => (
          <label
            key={i}
            className={cn(
              'flex items-center gap-2 rounded-md px-2 py-1',
              result && i === result.correct_answer && 'bg-green-100 dark:bg-green-950',
              result && i === chosen && !result.is_correct && 'bg-red-100 dark:bg-red-950',
            )}
          >
            <input
              type="radio"
              name={`question-${number}`}
              checked={chosen === i}
              disabled={result !== undefined}
              onChange={() => onChoose(i)}
            />
            {option}
          </label>
        ))}
      </div>
      {result && (
        <div className="mt-3 text-sm">
          <p className={cn('font-medium', result.is_correct ? 'text-green-700' : 'text-red-600')}>
            {result.is_correct
              ? 'Correct'
              : `Wrong. The answer is: ${question.options[result.correct_answer]}`}
          </p>
          <p className="mt-1 text-muted-foreground">
            {result.explanation}
            {result.page !== null && ` (p. ${result.page})`}
          </p>
        </div>
      )}
    </fieldset>
  )
}
