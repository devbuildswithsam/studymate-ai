// The layout every page shares (wireframe 6.1): sidebar on the left, page in the main area.
// SMA-31: "New chat" button and "Recent chats" list in the sidebar.
import { PlusIcon } from 'lucide-react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'

import { UserMenu } from '@/components/auth/UserMenu'
import { HealthStatus } from '@/components/HealthStatus'
import { NAV_ITEMS } from '@/components/layout/nav'
import { RecentChats } from '@/components/layout/RecentChats'
import { Button } from '@/components/ui/button'
import { Toaster } from '@/components/ui/sonner'
import { cn } from '@/lib/utils'

export function AppShell() {
  const { pathname } = useLocation()
  const inASavedChat = pathname.startsWith('/c/')

  return (
    <div className="flex min-h-svh bg-background text-foreground">
      <aside className="sticky top-0 flex h-svh w-64 shrink-0 flex-col border-r bg-muted/40 p-4">
        <p className="mb-4 px-2 text-lg font-semibold">StudyMate</p>
        <Button asChild variant="outline" className="mb-4 justify-start">
          <Link to="/">
            <PlusIcon aria-hidden />
            New chat
          </Link>
        </Button>
        <nav aria-label="Main" className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'} // otherwise "/" would match every page
              className={({ isActive }) =>
                cn(
                  'rounded-md px-2 py-1.5 text-sm hover:bg-muted',
                  // A saved chat (/c/...) is still the Chat page.
                  (isActive || (item.to === '/' && inASavedChat)) && 'bg-muted font-medium',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-6 flex min-h-0 flex-1 flex-col">
          <RecentChats />
        </div>
        <div className="border-t pt-4">
          <UserMenu /> {/* SMA-59: who is signed in, and Logout */}
        </div>
        <div className="px-2 pt-4">
          <HealthStatus />
        </div>
      </aside>
      <main className="flex-1 p-8">
        <Outlet /> {/* the current page renders here */}
      </main>
      <Toaster richColors position="top-center" /> {/* toast.error(...) from any page */}
    </div>
  )
}
