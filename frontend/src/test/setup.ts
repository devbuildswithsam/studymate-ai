// Runs before every test file (vite.config.ts -> test.setupFiles). SMA-24.
import '@testing-library/jest-dom/vitest' // adds toBeInTheDocument(), toHaveTextContent(), ...
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup() // remove what the test rendered, so tests never see each other's components
  vi.restoreAllMocks() // undo mocks such as a faked fetch
  vi.unstubAllGlobals()
})
