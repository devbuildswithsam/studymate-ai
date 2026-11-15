// Which page shows at which URL. Every page renders inside the shared AppShell.
import { Route, Routes } from 'react-router'

import { AppShell } from '@/components/layout/AppShell'
import { NAV_ITEMS } from '@/components/layout/nav'
import { PlaceholderPage } from '@/pages/PlaceholderPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        {NAV_ITEMS.map((item) => (
          <Route key={item.to} path={item.to} element={<PlaceholderPage title={item.label} />} />
        ))}
      </Route>
    </Routes>
  )
}
