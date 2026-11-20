// Create an account (SMA-59, ADR-0009). The account is logged in straight away.
import { useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router'

import { useMe, useRegister } from '@/api/auth'
import { AuthLayout } from '@/components/auth/AuthLayout'
import type { LoginState } from '@/components/auth/RequireAuth'
import { authErrorMessage, INPUT_CLASS, MIN_PASSWORD, passwordProblem } from '@/lib/authForms'

export function RegisterPage() {
  const me = useMe()
  const register = useRegister()
  const state = (useLocation().state as LoginState | null) ?? {}
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [problem, setProblem] = useState<string | null>(null)

  if (me.isSuccess) return <Navigate to={state.from ?? '/'} replace />

  function submit() {
    const tooWeak = passwordProblem(password)
    setProblem(tooWeak)
    if (tooWeak) return
    register.mutate({ email, password, name: name.trim() || undefined })
  }

  return (
    <AuthLayout
      title="Create account"
      submitLabel="Create account"
      busy={register.isPending}
      error={problem ?? (register.isError ? authErrorMessage(register.error) : null)}
      onSubmit={submit}
      footer={
        <p>
          Already have an account?{' '}
          <Link to="/login" state={state} className="underline">
            Log in
          </Link>
        </p>
      }
    >
      <label className="flex flex-col gap-1 text-sm">
        Name (optional)
        <input
          autoComplete="name"
          maxLength={200}
          value={name}
          onChange={(event) => setName(event.target.value)}
          className={INPUT_CLASS}
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Email
        <input
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className={INPUT_CLASS}
        />
      </label>
      <div className="flex flex-col gap-1">
        <label className="flex flex-col gap-1 text-sm">
          Password
          <input
            type="password"
            autoComplete="new-password" // lets the browser suggest a strong one
            required
            aria-describedby="password-hint"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={INPUT_CLASS}
          />
        </label>
        <span id="password-hint" className="text-xs text-muted-foreground">
          At least {MIN_PASSWORD} characters. A short sentence is easy to remember.
        </span>
      </div>
    </AuthLayout>
  )
}
