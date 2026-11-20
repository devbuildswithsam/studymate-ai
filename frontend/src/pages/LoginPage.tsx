// Log in (SMA-59, ADR-0009). After a successful login the app opens the page the user
// wanted before (RequireAuth remembered it), or the chat.
import { useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router'

import { useLogin, useMe } from '@/api/auth'
import { AuthLayout } from '@/components/auth/AuthLayout'
import { authErrorMessage, INPUT_CLASS } from '@/lib/authForms'
import type { LoginState } from '@/components/auth/RequireAuth'

export function LoginPage() {
  const me = useMe()
  const login = useLogin()
  const state = (useLocation().state as LoginState | null) ?? {}
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  // Signed in (just now, or already): go to the app. isSuccess, not data: after an
  // ended session the old user is still in data, and must not bounce us back.
  if (me.isSuccess) return <Navigate to={state.from ?? '/'} replace />

  return (
    <AuthLayout
      title="Log in"
      submitLabel="Log in"
      busy={login.isPending}
      error={login.isError ? authErrorMessage(login.error) : null}
      notice={state.expired ? 'Your session has ended. Please log in again.' : null}
      onSubmit={() => login.mutate({ email, password })}
      footer={
        <>
          <p>
            No account yet?{' '}
            <Link to="/register" state={state} className="underline">
              Create one
            </Link>
          </p>
          {/* ADR-0009: no email service in v1.1, so no reset link. */}
          <p>Forgot your password? Ask the admin to reset it.</p>
        </>
      }
    >
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
      <label className="flex flex-col gap-1 text-sm">
        Password
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className={INPUT_CLASS}
        />
      </label>
    </AuthLayout>
  )
}
