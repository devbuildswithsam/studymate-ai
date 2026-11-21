// Settings: personal access tokens for MCP clients (SMA-61, guide 7.2).
// A program like MCP Inspector or Claude Desktop sends a token as
// "Authorization: Bearer <token>" to /mcp and then acts as you. The token is shown ONCE:
// the server keeps only its hash, so nobody (not even StudyMate) can show it again.
import { useState, type FormEvent } from 'react'

import { useHealth } from '@/api/health'
import {
  EXPIRY_CHOICES,
  useCreateToken,
  useRevokeToken,
  useTokens,
  type AccessToken,
  type NewAccessToken,
} from '@/api/tokens'
import { CopyButton } from '@/components/chat/CopyButton'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { friendlyError } from '@/lib/errors'

const day = (iso: string) => new Date(iso).toLocaleDateString()

export function SettingsPage() {
  const { data: health } = useHealth()

  return (
    <section className="max-w-2xl">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <h2 className="mt-6 text-lg font-semibold">Access tokens for MCP clients</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        A token lets a program such as MCP Inspector or Claude Desktop use your StudyMate tools
        (tasks, notes, documents) as you. In the program, use the URL{' '}
        <code>http://127.0.0.1:8000/mcp</code> and paste the token as a Bearer token. Treat it like
        a password, and revoke tokens you no longer use.
      </p>
      {health?.auth_mode === 'local' && (
        <p className="mt-3 rounded-md bg-muted px-3 py-2 text-sm">
          The app is in local mode: /mcp needs no token, programs on this computer connect directly.
          Tokens are used when accounts are on (AUTH_MODE=jwt).
        </p>
      )}
      <NewToken />
      <TokenList />
    </section>
  )
}

function NewToken() {
  const create = useCreateToken()
  const [name, setName] = useState('')
  const [days, setDays] = useState(90)
  const [made, setMade] = useState<NewAccessToken | null>(null)

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { name, expires_in_days: days },
      {
        onSuccess: (token) => {
          setMade(token)
          setName('')
        },
      },
    )
  }

  if (made) {
    return (
      <div
        role="status"
        className="mt-6 rounded-md border border-amber-500 bg-amber-50 p-4 dark:bg-amber-950"
      >
        <p className="text-sm font-medium">
          Copy your new token now. You won't be able to see it again.
        </p>
        <div className="mt-2 flex items-center gap-2">
          <code className="min-w-0 flex-1 break-all rounded bg-background px-2 py-1 text-sm">
            {made.token}
          </code>
          <CopyButton text={made.token} label="Copy token" />
        </div>
        {/* Forget it in this page too: once closed it is gone for good. */}
        <Button variant="outline" size="sm" className="mt-3" onClick={() => setMade(null)}>
          I've copied it
        </Button>
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="mt-6 flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-sm">
        Token name
        <input
          required
          maxLength={100}
          placeholder="e.g. MCP Inspector"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="rounded-md border bg-background px-3 py-2"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Expires after
        <select
          value={days}
          onChange={(event) => setDays(Number(event.target.value))}
          className="rounded-md border bg-background px-3 py-2"
        >
          {EXPIRY_CHOICES.map((choice) => (
            <option key={choice.days} value={choice.days}>
              {choice.label}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" disabled={create.isPending || !name.trim()}>
        Create token
      </Button>
      {create.isError && (
        <p role="alert" className="w-full text-sm text-red-600">
          {friendlyError(create.error)}
        </p>
      )}
    </form>
  )
}

function TokenList() {
  const { data: tokens, error } = useTokens()
  const revoke = useRevokeToken()

  if (error) return <p className="mt-6 text-sm text-red-600">{friendlyError(error)}</p>
  if (!tokens) return null
  if (tokens.length === 0) {
    return <p className="mt-6 text-sm text-muted-foreground">No tokens yet.</p>
  }
  return (
    <ul className="mt-6 flex flex-col divide-y rounded-md border">
      {tokens.map((token) => (
        <li key={token.id} aria-label={token.name} className="flex items-center gap-3 p-3">
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-2 font-medium">
              {token.name}
              {isExpired(token) && <Badge variant="secondary">Expired</Badge>}
            </p>
            <p className="text-xs text-muted-foreground">
              <code>{token.prefix}…</code> · created {day(token.created_at)} ·{' '}
              {isExpired(token) ? 'expired' : 'expires'} {day(token.expires_at)} ·{' '}
              {token.last_used_at ? `last used ${day(token.last_used_at)}` : 'never used'}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={revoke.isPending}
            onClick={() => revoke.mutate(token.id)}
          >
            Revoke
          </Button>
        </li>
      ))}
    </ul>
  )
}

function isExpired(token: AccessToken): boolean {
  return new Date(token.expires_at).getTime() <= Date.now()
}
