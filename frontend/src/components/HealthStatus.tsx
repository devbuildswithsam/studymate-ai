// Shows whether the backend answers GET /api/health. SMA-24.
import { useHealth } from '@/api/health'
import { cn } from '@/lib/utils'

export function HealthStatus() {
  const { data, error, isPending } = useHealth()

  let dot = 'bg-muted-foreground'
  let label = 'Checking API…'
  let detail = ''
  if (data) {
    dot = 'bg-green-600'
    label = 'API online'
    detail = `v${data.version} · ${data.auth_mode} auth`
  } else if (error) {
    dot = 'bg-red-600'
    label = 'API offline'
    detail = error.message
  }

  return (
    // role="status": screen readers announce it when the text changes.
    <div role="status" className="text-xs text-muted-foreground">
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className={cn('size-2 rounded-full', isPending && 'animate-pulse', dot)}
        />
        <span>{label}</span>
      </div>
      {detail && <p className="mt-1 break-words">{detail}</p>}
    </div>
  )
}
