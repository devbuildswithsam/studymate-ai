/// <reference types="vitest/config" />
import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // "@/components/x" instead of "../../components/x" (also set in tsconfig for types).
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    // Dev proxy: React calls relative paths like /api/health and Vite forwards them to
    // FastAPI. The browser sees one origin, so no CORS, and no backend URL in the code.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    // Vitest: jsdom is a fake browser inside Node, so components render without a real one.
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Tests run in New York time (west of UTC). In India (UTC+5:30) most "UTC instead of
    // local day" bugs stay hidden; here they show up. SMA-40.
    env: { TZ: 'America/New_York' },
  },
})
