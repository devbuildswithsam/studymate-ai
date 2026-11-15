// Which page shows at which URL. Every page renders inside the shared AppShell.
import { Route, Routes } from 'react-router'

import { AppShell } from '@/components/layout/AppShell'
import { NAV_ITEMS } from '@/components/layout/nav'
import { ChatPage } from '@/pages/ChatPage'
import { PlaceholderPage } from '@/pages/PlaceholderPage'

// Pages that exist so far; the rest show a placeholder until their ticket is done.
const PAGES: Record<string, () => React.JSX.Element> = {
  '/': ChatPage,
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        {NAV_ITEMS.map((item) => {
          const Page = PAGES[item.to]
          return (
            <Route
              key={item.to}
              path={item.to}
              element={Page ? <Page /> : <PlaceholderPage title={item.label} />}
            />
          )
        })}
      </Route>
    </Routes>
  )
}
