// Model dropdown + "Use fallback" toggle (wireframe 6.9). SMA-26 (test-first).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ModelInfo } from '@/api/models'
import { ModelSelector } from '@/components/chat/ModelSelector'

const MODELS: ModelInfo[] = [
  {
    id: 'gemini-3.5-flash',
    provider: 'gemini',
    display_name: 'Gemini 3.5 Flash',
    supports_tools: true,
    supports_json: true,
    status: 'available',
  },
  {
    id: 'openai/gpt-oss-120b',
    provider: 'groq',
    display_name: 'GPT-OSS 120B (Groq)',
    supports_tools: true,
    supports_json: true,
    status: 'rate_limited',
  },
  {
    id: 'other',
    provider: 'openrouter',
    display_name: 'Other model',
    supports_tools: false,
    supports_json: false,
    status: 'no_key',
  },
]

function renderSelector(props: Partial<Parameters<typeof ModelSelector>[0]> = {}) {
  const handlers = { onModelChange: vi.fn(), onAllowFallbackChange: vi.fn() }
  render(
    <ModelSelector
      models={MODELS}
      model="gemini-3.5-flash"
      allowFallback
      {...handlers}
      {...props}
    />,
  )
  return handlers
}

const select = () => screen.getByRole('combobox', { name: 'Model' })

describe('ModelSelector', () => {
  it('lists every model with its status', () => {
    renderSelector()

    const options = within(select()).getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual([
      'Gemini 3.5 Flash — available',
      'GPT-OSS 120B (Groq) — rate-limited',
      'Other model — no API key',
    ])
  })

  it('disables models without an API key', () => {
    renderSelector()

    expect(screen.getByRole('option', { name: /Other model/ })).toBeDisabled()
    expect(screen.getByRole('option', { name: /GPT-OSS/ })).toBeEnabled() // may recover soon
  })

  it('shows the selected model and reports a new choice by id', async () => {
    const { onModelChange } = renderSelector()

    expect(select()).toHaveValue('gemini-3.5-flash')
    await userEvent.selectOptions(select(), 'openai/gpt-oss-120b')

    expect(onModelChange).toHaveBeenCalledWith('openai/gpt-oss-120b')
  })

  it('has a "Use fallback if the model fails" checkbox that reports changes', async () => {
    const { onAllowFallbackChange } = renderSelector({ allowFallback: true })

    const toggle = screen.getByRole('checkbox', { name: 'Use fallback if the model fails' })
    expect(toggle).toBeChecked()
    await userEvent.click(toggle)

    expect(onAllowFallbackChange).toHaveBeenCalledWith(false)
  })
})
