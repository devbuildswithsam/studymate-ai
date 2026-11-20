// The frame around Login and Register: no sidebar, just a centred card (SMA-59).
import type { FormEvent, ReactNode } from 'react'

import { Button } from '@/components/ui/button'

type Props = {
  title: string
  submitLabel: string
  busy: boolean
  error: string | null
  onSubmit: () => void
  children: ReactNode // the inputs
  footer: ReactNode // links under the form
  notice?: string | null // e.g. "Your session has ended"
}

export function AuthLayout(props: Props) {
  function submit(event: FormEvent) {
    event.preventDefault() // stay on the page: React sends the request
    props.onSubmit()
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
      <main className="w-full max-w-sm rounded-xl border bg-background p-8 shadow-sm">
        <p className="mb-6 text-lg font-semibold">StudyMate</p>
        <h1 className="mb-4 text-2xl font-semibold">{props.title}</h1>
        {props.notice && (
          <p className="mb-4 rounded-md bg-muted px-3 py-2 text-sm">{props.notice}</p>
        )}
        <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
          {props.children}
          {props.error && (
            <p role="alert" className="text-sm text-red-600">
              {props.error}
            </p>
          )}
          <Button type="submit" disabled={props.busy} className="mt-2">
            {props.busy ? 'Please wait…' : props.submitLabel}
          </Button>
        </form>
        <div className="mt-6 flex flex-col gap-2 text-sm text-muted-foreground">{props.footer}</div>
      </main>
    </div>
  )
}
