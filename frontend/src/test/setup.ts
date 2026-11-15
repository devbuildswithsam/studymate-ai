// Runs before every test file (vite.config.ts -> test.setupFiles). SMA-24.
import '@testing-library/jest-dom/vitest' // adds toBeInTheDocument(), toHaveTextContent(), ...
import { cleanup } from '@testing-library/react'
import { toast } from 'sonner'
import { afterEach, vi } from 'vitest'

// jsdom has no window.matchMedia, but the toast component (Sonner) uses it to follow
// light/dark mode. A minimal stand-in that always answers "no match".
// Set directly (not vi.stubGlobal), so the afterEach below doesn't remove it.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {}, // older API, still used by some libraries
    removeListener: () => {},
    dispatchEvent: () => false,
  }),
})

afterEach(() => {
  cleanup() // remove what the test rendered, so tests never see each other's components
  // Sonner keeps toasts in module memory, not in the DOM, so cleanup() can't remove them:
  // without this, a toast from one test showed up in the next (a false pass, SMA-25).
  toast.dismiss()
  vi.restoreAllMocks() // undo mocks such as a faked fetch
  vi.unstubAllGlobals()
})
