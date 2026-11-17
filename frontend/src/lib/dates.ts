// Date helpers. SMA-40.

const DAY_MS = 24 * 60 * 60 * 1000
const WEEKDAY = new Intl.DateTimeFormat('en-GB', { weekday: 'short' }) // "Fri"
const DAY_MONTH = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }) // "24 Nov"

/** "2026-11-20" -> that day at local midnight. (new Date("2026-11-20") would be UTC.) */
function localDay(isoDate: string): Date {
  const [year, month, day] = isoDate.split('-').map(Number)
  return new Date(year, month - 1, day)
}

/** Today's date at local midnight. */
function startOfDay(moment: Date): Date {
  return new Date(moment.getFullYear(), moment.getMonth(), moment.getDate())
}

/**
 * The label on a task card: "Due today", "Due tomorrow", "Due Fri" (within a week),
 * "Due 24 Nov", or "Overdue · 15 Nov". Compares calendar days in the user's time zone.
 */
export function dueLabel(
  dueDate: string,
  now: Date = new Date(),
): { label: string; overdue: boolean } {
  const due = localDay(dueDate)
  const days = Math.round((due.getTime() - startOfDay(now).getTime()) / DAY_MS)
  if (days < 0) return { label: `Overdue · ${DAY_MONTH.format(due)}`, overdue: true }
  if (days === 0) return { label: 'Due today', overdue: false }
  if (days === 1) return { label: 'Due tomorrow', overdue: false }
  if (days < 7) return { label: `Due ${WEEKDAY.format(due)}`, overdue: false }
  return { label: `Due ${DAY_MONTH.format(due)}`, overdue: false }
}
