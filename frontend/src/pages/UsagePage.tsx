// Admin: AI usage per day and model, from llm_calls (SMA-68). Totals only: no user,
// chat or question is shown. The backend answers 403 to anyone but an admin.
import { useUsage } from '@/api/admin'
import { friendlyError } from '@/lib/errors'

const number = (n: number) => n.toLocaleString('en-US')

export function UsagePage() {
  const usage = useUsage()

  return (
    <section className="max-w-4xl">
      <h1 className="text-2xl font-semibold">AI usage</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Calls to the AI models in the last {usage.data?.days ?? 30} days, per day (UTC) and model,
        for all users together. Failures include timeouts and rate limits; a cached answer makes no
        call.
      </p>
      {usage.error && (
        <p role="alert" className="mt-6 text-sm text-red-600">
          {friendlyError(usage.error)}
        </p>
      )}
      {usage.data && usage.data.rows.length === 0 && (
        <p className="mt-6 text-sm text-muted-foreground">No AI calls in this period.</p>
      )}
      {usage.data && usage.data.rows.length > 0 && (
        <table className="mt-6 w-full text-left text-sm">
          <thead className="border-b text-muted-foreground">
            <tr>
              <th className="py-2 font-medium">Day</th>
              <th className="py-2 font-medium">Model</th>
              <th className="py-2 text-right font-medium">Calls</th>
              <th className="py-2 text-right font-medium">Failures</th>
              <th className="py-2 text-right font-medium">Tokens in</th>
              <th className="py-2 text-right font-medium">Tokens out</th>
            </tr>
          </thead>
          <tbody>
            {usage.data.rows.map((row) => (
              <tr key={`${row.day} ${row.provider} ${row.model}`} className="border-b">
                <td className="py-2">{row.day}</td>
                <td className="py-2">{row.model}</td>
                <td className="py-2 text-right">{number(row.calls)}</td>
                <td className={row.failures ? 'py-2 text-right text-red-600' : 'py-2 text-right'}>
                  {number(row.failures)}
                </td>
                <td className="py-2 text-right">{number(row.tokens_in)}</td>
                <td className="py-2 text-right">{number(row.tokens_out)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="font-medium">
            <tr>
              <td className="py-2">Total</td>
              <td />
              <td className="py-2 text-right">{number(usage.data.totals.calls)}</td>
              <td className="py-2 text-right">{number(usage.data.totals.failures)}</td>
              <td className="py-2 text-right">{number(usage.data.totals.tokens_in)}</td>
              <td className="py-2 text-right">{number(usage.data.totals.tokens_out)}</td>
            </tr>
          </tfoot>
        </table>
      )}
    </section>
  )
}
