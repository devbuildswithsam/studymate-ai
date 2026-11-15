// The layout every page shares (wireframe 6.1): sidebar on the left, page in the main area.
import { NavLink, Outlet } from 'react-router'

import { HealthStatus } from '@/components/HealthStatus'
import { NAV_ITEMS } from '@/components/layout/nav'
import { cn } from '@/lib/utils'

export function AppShell() {
  return (
    <div className="flex min-h-svh bg-background text-foreground">
      <aside className="flex w-60 shrink-0 flex-col border-r bg-muted/40 p-4">
        <p className="mb-6 px-2 text-lg font-semibold">StudyMate</p>
        <nav aria-label="Main" className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'} // otherwise "/" would match every page
              className={({ isActive }) =>
                cn(
                  'rounded-md px-2 py-1.5 text-sm hover:bg-muted',
                  isActive && 'bg-muted font-medium',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-2 pt-4">
          <HealthStatus />
        </div>
      </aside>
      <main className="flex-1 p-8">
        <Outlet /> {/* the current page renders here */}
      </main>
    </div>
  )
}
