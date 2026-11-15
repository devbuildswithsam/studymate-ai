import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import prettier from 'eslint-config-prettier'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      prettier, // last: turns off rules that clash with Prettier's formatting
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    // shadcn/ui components are generated code that also exports style helpers
    // (e.g. buttonVariants) on purpose. Don't edit them to please this dev-only rule.
    files: ['src/components/ui/**'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
])
