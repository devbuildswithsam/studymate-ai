// Due-date labels on task cards (wireframe 6.6: "Due Fri", "Due Today"). SMA-40, test-first.
import { describe, expect, it } from 'vitest'

import { dueLabel } from '@/lib/dates'

const TODAY = new Date(2026, 10, 17, 15, 30) // Tue 17 Nov 2026, afternoon (local time)

describe('dueLabel', () => {
  it.each([
    ['2026-11-17', 'Due today', false],
    ['2026-11-18', 'Due tomorrow', false],
    ['2026-11-20', 'Due Fri', false], // within the next week: the weekday is enough
    ['2026-11-23', 'Due Mon', false],
    ['2026-11-24', 'Due 24 Nov', false], // a week or more away: the date
    ['2026-11-16', 'Overdue · 16 Nov', true],
    ['2026-10-30', 'Overdue · 30 Oct', true],
  ])('%s -> %s', (due, label, overdue) => {
    expect(dueLabel(due, TODAY)).toEqual({ label, overdue })
  })

  it('uses the local calendar day, not UTC', () => {
    // 00:30 on 18 Nov in India is still 17 Nov in UTC: "tomorrow" must follow the user's day.
    const justAfterMidnight = new Date(2026, 10, 18, 0, 30)

    expect(dueLabel('2026-11-18', justAfterMidnight)).toEqual({
      label: 'Due today',
      overdue: false,
    })
  })
})

describe('dueLabel west of UTC', () => {
  it('runs in New York time (vite.config.ts), so UTC mistakes show', () => {
    expect(new Date(2026, 10, 17, 9, 0).getTimezoneOffset()).toBeGreaterThan(0)
  })

  it('names the right day', () => {
    // new Date('2026-11-20') means UTC midnight: in New York that is still Thursday evening,
    // so a Friday task would be labelled "Due Thu".
    const tuesday = new Date(2026, 10, 17, 9, 0)

    expect(dueLabel('2026-11-20', tuesday).label).toBe('Due Fri')
    expect(dueLabel('2026-11-24', tuesday).label).toBe('Due 24 Nov')
  })
})
