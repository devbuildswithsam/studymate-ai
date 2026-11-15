// Model dropdown + "Use fallback" toggle in the chat header (wireframe 6.9). SMA-26.
// Native <select> and checkbox: accessible by default (keyboard, screen readers, mobile).
import type { ModelInfo, ModelStatus } from '@/api/models'

const STATUS_LABEL: Record<ModelStatus, string> = {
  available: 'available',
  rate_limited: 'rate-limited',
  no_key: 'no API key',
}

type Props = {
  models: ModelInfo[]
  model: string
  onModelChange: (modelId: string) => void
  allowFallback: boolean
  onAllowFallbackChange: (allow: boolean) => void
}

export function ModelSelector({
  models,
  model,
  onModelChange,
  allowFallback,
  onAllowFallbackChange,
}: Props) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
      <label className="flex items-center gap-2">
        <span className="text-muted-foreground">Model</span>
        <select
          aria-label="Model"
          value={model}
          onChange={(event) => onModelChange(event.target.value)}
          className="h-8 rounded-md border bg-background px-2"
        >
          {models.map((m) => (
            // No key = it can only fail, so it can't be chosen. Rate-limited may recover soon.
            <option key={m.id} value={m.id} disabled={m.status === 'no_key'}>
              {`${m.display_name} — ${STATUS_LABEL[m.status]}`}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={allowFallback}
          onChange={(event) => onAllowFallbackChange(event.target.checked)}
          className="size-4"
        />
        Use fallback if the model fails
      </label>
    </div>
  )
}
