// Who is signed in, Settings (SMA-61) and Logout (SMA-59). In local mode there is only the
// local user and nothing to log out of, so Logout is hidden.
import { LogOutIcon, SettingsIcon } from 'lucide-react'
import { Link } from 'react-router'

import { useLogout, useMe } from '@/api/auth'
import { useHealth } from '@/api/health'
import { Button } from '@/components/ui/button'

export function UserMenu() {
  const { data: user } = useMe()
  const { data: health } = useHealth()
  const logout = useLogout()

  if (!user) return null
  return (
    <div className="flex items-center gap-2 px-2">
      <div className="min-w-0 flex-1 text-sm">
        {user.name && <p className="truncate font-medium">{user.name}</p>}
        <p className="truncate text-xs text-muted-foreground">{user.email}</p>
      </div>
      {/* SMA-61: access tokens for MCP clients */}
      <Button asChild variant="ghost" size="icon" title="Settings">
        <Link to="/settings" aria-label="Settings">
          <SettingsIcon aria-hidden />
        </Link>
      </Button>
      {health?.auth_mode === 'jwt' && (
        <Button
          variant="ghost"
          size="icon"
          aria-label="Log out"
          title="Log out"
          disabled={logout.isPending}
          // RequireAuth sees "nobody" afterwards and shows Login.
          onClick={() => logout.mutate()}
        >
          <LogOutIcon aria-hidden />
        </Button>
      )}
    </div>
  )
}
