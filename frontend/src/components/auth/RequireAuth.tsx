// The gate in front of every app page (SMA-59). Pages inside it can assume a signed-in
// user. The real protection is the backend (every route checks the cookie); this gate
// makes the browser show Login instead of a page full of 401 errors.
import { Navigate, Outlet, useLocation } from 'react-router'

import { isUnauthorized, useMe } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { friendlyError } from '@/lib/errors'

/** What Login needs to know: where to go back to, and whether a session just ended. */
export type LoginState = { from?: string; expired?: boolean }

export function RequireAuth() {
  const me = useMe()
  const location = useLocation()

  if (me.isError && isUnauthorized(me.error)) {
    // We knew a user before (me.data from an earlier answer), so their session ended.
    const state: LoginState = {
      from: location.pathname + location.search,
      expired: me.data !== undefined,
    }
    return <Navigate to="/login" replace state={state} />
  }
  if (me.data) return <Outlet /> // also while a later check fails for another reason
  if (me.isError) {
    return (
      <div role="alert" className="flex min-h-svh flex-col items-center justify-center gap-4 p-8">
        <p>{friendlyError(me.error)}</p>
        <Button variant="outline" onClick={() => void me.refetch()}>
          Try again
        </Button>
      </div>
    )
  }
  return (
    <p role="status" className="p-8 text-muted-foreground">
      Loading…
    </p>
  )
}
