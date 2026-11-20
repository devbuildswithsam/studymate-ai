// Login, register, protected pages and logout (SMA-59, ADR-0009). Test-first.
// A fake backend plays /api/auth/*: one account, a session that can end.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { User } from '@/api/auth'
import { mockApi, renderApp } from '@/test/render'

const ADA: User = { id: 'u1', email: 'ada@example.com', name: 'Ada' }
const GRACE: User = { id: 'u3', email: 'grace@example.com', name: 'Grace' }
const PASSWORD = 'correct horse battery' // both accounts use it
const ADAS_TASK = {
  id: 't1',
  title: "Ada's private task",
  description: null,
  due_date: null,
  priority: 'medium',
  status: 'todo',
  document_id: null,
  created_by: 'user',
  created_at: '2026-11-20T09:00:00Z',
  completed_at: null,
}
const LOGIN_FAILED = 'Email or password is incorrect.'

const json = (body: unknown, status = 200) => Response.json(body, { status })
const unauthorized = (message = 'Please log in.') =>
  json({ error: { code: 'unauthorized', message } }, 401)

/** A fake backend in AUTH_MODE=jwt. `session` is who the cookie names (null: nobody). */
function authBackend(options: { session?: User | null; mode?: 'jwt' | 'local' } = {}) {
  const state = { session: options.session ?? null, calls: [] as string[] }
  const fetch = mockApi({
    '/api/health': {
      body: { status: 'ok', version: '1.0.0', env: 'test', auth_mode: options.mode ?? 'jwt' },
    },
    'GET /api/auth/me': async () => (state.session ? json(state.session) : unauthorized()),
    'POST /api/auth/login': async (init) => {
      state.calls.push('login')
      const body = JSON.parse(String(init?.body))
      const account = [ADA, GRACE].find((user) => user.email === body.email)
      if (!account || body.password !== PASSWORD) return unauthorized(LOGIN_FAILED)
      state.session = account
      return json(account)
    },
    'POST /api/auth/register': async (init) => {
      state.calls.push('register')
      const body = JSON.parse(String(init?.body))
      if (body.email === ADA.email) {
        return json(
          { error: { code: 'conflict', message: 'An account with this email already exists.' } },
          409,
        )
      }
      state.session = { id: 'u2', email: body.email, name: body.name ?? null }
      return json(state.session, 201)
    },
    'POST /api/auth/logout': async () => {
      state.calls.push('logout')
      state.session = null
      return new Response(null, { status: 204 })
    },
    // Ordinary data routes, also protected: 401 once the session has ended.
    '/api/conversations': async () => (state.session ? json([]) : unauthorized()),
    '/api/notes': async () => (state.session ? json([]) : unauthorized()),
    '/api/tasks': async () => {
      if (!state.session) return unauthorized()
      if (state.session.id === ADA.id) return json([ADAS_TASK])
      if (state.session.id === GRACE.id) return new Promise<Response>(() => {}) // never answers
      return json([])
    },
  })
  return { state, fetch }
}

async function logIn(email = ADA.email, password = PASSWORD) {
  await userEvent.type(await screen.findByLabelText('Email'), email)
  await userEvent.type(screen.getByLabelText('Password'), password)
  await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
}

describe('protected pages', () => {
  it('sends a logged-out visitor to Login, then back to the page they wanted', async () => {
    authBackend()
    renderApp('/tasks', { user: null })

    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()

    await logIn()

    expect(await screen.findByRole('heading', { level: 1, name: 'Tasks' })).toBeInTheDocument()
  })

  it('shows no app page while "who am I?" is still loading', async () => {
    mockApi({ 'GET /api/auth/me': () => new Promise<Response>(() => {}) }) // never answers
    renderApp('/tasks', { user: null })

    expect(await screen.findByText('Loading…')).toBeVisible()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Tasks' })).not.toBeInTheDocument()
  })

  it('explains an unreachable server instead of showing the app', async () => {
    mockApi({ 'GET /api/auth/me': () => Promise.reject(new TypeError('Failed to fetch')) })
    renderApp('/tasks', { user: null })

    expect(await screen.findByText("Can't reach the server. Is the backend running?")).toBeVisible()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })

  it("never shows the previous person's data to the next one", async () => {
    // Ada's tasks are in the cache; her session ends; Grace logs in at the same computer.
    // Grace's tasks request never answers, so anything shown comes from the old cache.
    const { state } = authBackend({ session: ADA })
    renderApp('/tasks', { user: ADA })
    expect(await screen.findByText("Ada's private task")).toBeVisible()

    state.session = null
    await userEvent.click(screen.getByRole('link', { name: 'Notes' })) // any request -> 401
    await logIn(GRACE.email, PASSWORD)

    expect(await screen.findByRole('heading', { level: 1, name: 'Notes' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Tasks' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Tasks' })).toBeInTheDocument()
    expect(screen.queryByText("Ada's private task")).not.toBeInTheDocument()
  })

  it('shows a friendly message when the session has ended', async () => {
    // The app believed Ada was signed in, but the backend no longer accepts her cookie
    // (8 hours passed): the next "who am I?" answers 401.
    authBackend({ session: null })
    renderApp('/tasks', { user: ADA })

    expect(await screen.findByText('Your session has ended. Please log in again.')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Log in' })).toBeInTheDocument()
  })

  it('notices an ended session from any request, not only "who am I?"', async () => {
    const { state } = authBackend({ session: ADA })
    renderApp('/', { user: ADA })
    expect(await screen.findByRole('heading', { level: 1, name: 'Chat' })).toBeInTheDocument()

    state.session = null // the cookie expires while the page is open
    await userEvent.click(screen.getByRole('link', { name: 'Tasks' })) // GET /api/tasks -> 401 below

    expect(await screen.findByText('Your session has ended. Please log in again.')).toBeVisible()
  })
})

describe('Login page', () => {
  it('shows the backend message for a wrong password and stays', async () => {
    authBackend()
    renderApp('/login', { user: null })

    await logIn(ADA.email, 'wrong password')

    expect(await screen.findByText(LOGIN_FAILED)).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Log in' })).toBeInTheDocument()
  })

  it('shows "too many tries" as the backend says it, not as a busy AI', async () => {
    authBackend()
    mockApi({
      'GET /api/auth/me': async () => unauthorized(),
      'POST /api/auth/login': async () =>
        json({ error: { code: 'rate_limited', message: 'Too many failed logins.' } }, 429),
    })
    renderApp('/login', { user: null })

    await logIn()

    expect(await screen.findByText('Too many failed logins.')).toBeVisible()
  })

  it('says what to do about a forgotten password', async () => {
    authBackend()
    renderApp('/login', { user: null })

    expect(await screen.findByText(/forgot your password\? ask the admin/i)).toBeVisible()
  })

  it('sends a signed-in user straight to the app', async () => {
    authBackend({ session: ADA })
    renderApp('/login', { user: ADA })

    expect(await screen.findByRole('heading', { level: 1, name: 'Chat' })).toBeInTheDocument()
  })
})

describe('Register page', () => {
  async function fillIn(email: string, password: string) {
    await userEvent.type(await screen.findByLabelText('Name (optional)'), 'Grace')
    await userEvent.type(screen.getByLabelText('Email'), email)
    await userEvent.type(screen.getByLabelText('Password'), password)
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
  }

  it('checks the password length before asking the server', async () => {
    const { state } = authBackend()
    renderApp('/register', { user: null })

    await fillIn('grace@example.com', '1234567') // 7 characters

    expect(await screen.findByText('Use at least 8 characters.')).toBeVisible()
    expect(state.calls).not.toContain('register')
  })

  it('creates the account and opens the app', async () => {
    authBackend()
    renderApp('/register', { user: null })

    await fillIn('grace@example.com', 'a long enough password')

    expect(await screen.findByRole('heading', { level: 1, name: 'Chat' })).toBeInTheDocument()
    expect(await screen.findByText('grace@example.com')).toBeVisible() // in the sidebar
  })

  it('explains a used email and links to Login', async () => {
    authBackend()
    renderApp('/register', { user: null })

    await fillIn(ADA.email, 'a long enough password')

    expect(await screen.findByText('An account with this email already exists.')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
  })
})

describe('the signed-in user and Logout', () => {
  it("shows who is signed in, and Logout ends the session and forgets the user's data", async () => {
    const { state } = authBackend({ session: ADA })
    const { queryClient } = renderApp('/tasks', { user: ADA })
    const sidebar = await screen.findByRole('complementary')
    expect(await within(sidebar).findByText('Ada')).toBeVisible()
    expect(within(sidebar).getByText('ada@example.com')).toBeVisible()

    await userEvent.click(await within(sidebar).findByRole('button', { name: 'Log out' }))

    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(state.calls).toContain('logout')
    // Nothing of Ada's stays in the cache for the next person at this computer.
    await waitFor(() => {
      const cached = queryClient
        .getQueryCache()
        .getAll()
        .map((q) => q.queryKey[0])
      expect(cached).not.toContain('tasks')
      expect(cached).not.toContain('conversation-list')
    })
  })

  it('has no Logout in local mode (there is only the local user)', async () => {
    authBackend({ session: ADA, mode: 'local' })
    renderApp('/', { user: ADA })

    expect(await screen.findByRole('heading', { level: 1, name: 'Chat' })).toBeInTheDocument()
    expect(await screen.findByText('API online')).toBeVisible() // health has loaded
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument()
  })
})
