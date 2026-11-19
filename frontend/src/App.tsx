// Which page shows at which URL. Every page renders inside the shared AppShell.
import { Route, Routes, useLocation, useParams } from 'react-router'

import type { DocumentRef } from '@/api/conversations'

import { AppShell } from '@/components/layout/AppShell'
import { NAV_ITEMS } from '@/components/layout/nav'
import { ChatPage } from '@/pages/ChatPage'
import { DocumentPage } from '@/pages/DocumentPage'
import { DocumentsPage } from '@/pages/DocumentsPage'
import { NotesPage } from '@/pages/NotesPage'
import { PlaceholderPage } from '@/pages/PlaceholderPage'
import { StudyPage } from '@/pages/StudyPage'
import { TasksPage } from '@/pages/TasksPage'

/**
 * The chat page: "/" is a new chat, "/c/:conversationId" a saved one (SMA-31).
 *
 * `key` decides when React starts the page afresh (empty draft, default toggles):
 * - opening another chat, or "New chat" (every visit to "/" gets a new location.key);
 * - but NOT when a new chat moves to its own address after its first answer: ChatPage
 *   passes its key along in the navigation state, so nothing on screen is lost.
 */
function ChatRoute() {
  const { conversationId } = useParams()
  const location = useLocation()
  const keptKey = (location.state as { pageKey?: string } | null)?.pageKey
  const pageKey = keptKey ?? conversationId ?? location.key
  return <ChatPage key={pageKey} pageKey={pageKey} conversationId={conversationId} />
}

/** The study chat: "/study" is a new one, "/study/:conversationId" a saved one (SMA-49).
 * Same page-key rule as ChatRoute: a new chat moving to its own address stays on screen. */
function StudyRoute() {
  const { conversationId } = useParams()
  const location = useLocation()
  const keptKey = (location.state as { pageKey?: string } | null)?.pageKey
  const pageKey = keptKey ?? conversationId ?? location.key
  // SMA-50: "Chat with this document" arrives with the document already picked.
  const initialDocuments = (location.state as { documents?: DocumentRef[] } | null)?.documents
  return (
    <StudyPage
      key={pageKey}
      pageKey={pageKey}
      conversationId={conversationId}
      initialDocuments={initialDocuments}
    />
  )
}

// Pages that exist so far; the rest show a placeholder until their ticket is done.
const PAGES: Record<string, () => React.JSX.Element> = {
  '/': ChatRoute,
  '/documents': DocumentsPage,
  '/study': StudyRoute,
  '/notes': NotesPage,
  '/tasks': TasksPage,
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
        <Route path="/c/:conversationId" element={<ChatRoute />} />
        <Route path="/study/:conversationId" element={<StudyRoute />} />
        <Route path="/documents/:documentId" element={<DocumentPage />} />
        <Route path="/notes/:noteId" element={<NotesPage />} />
      </Route>
    </Routes>
  )
}
