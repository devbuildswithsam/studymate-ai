// The app shell from wireframe 6.1: sidebar navigation + main area. SMA-24 (test-first).
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const PAGES = [
  ['Chat', '/'],
  ['Documents', '/documents'],
  ['Study', '/study'],
  ['Quizzes', '/quizzes'],
  ['Tasks', '/tasks'],
  ['Notes', '/notes'],
  ['Progress', '/progress'],
] as const

describe('App shell', () => {
  beforeEach(() => {
    mockApi({
      '/api/health': { body: { status: 'ok', version: '0.1.0', env: 'test', auth_mode: 'local' } },
    })
  })

  it('shows the app name and a link to every page in the sidebar', () => {
    renderApp('/')

    expect(screen.getByText('StudyMate')).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual(PAGES)
  })

  it.each(PAGES)('shows the %s page in the main area at %s', (name, url) => {
    renderApp(url)

    const main = screen.getByRole('main')
    expect(within(main).getByRole('heading', { level: 1, name })).toBeInTheDocument()
  })

  it('marks the current page link', () => {
    renderApp('/notes')

    expect(screen.getByRole('link', { name: 'Notes' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Chat' })).not.toHaveAttribute('aria-current')
  })

  it('changes page when a sidebar link is clicked', async () => {
    renderApp('/')

    await userEvent.click(screen.getByRole('link', { name: 'Tasks' }))

    expect(screen.getByRole('heading', { level: 1, name: 'Tasks' })).toBeInTheDocument()
  })
})
