// The pages in the sidebar, in order (project guide, section 6). Used by AppShell and App routes.
export const NAV_ITEMS = [
  { label: 'Chat', to: '/' },
  { label: 'Documents', to: '/documents' },
  { label: 'Study', to: '/study' },
  { label: 'Quizzes', to: '/quizzes' },
  { label: 'Flashcards', to: '/flashcards' }, // SMA-64
  { label: 'Tasks', to: '/tasks' },
  { label: 'Notes', to: '/notes' },
  { label: 'Progress', to: '/progress' },
] as const
