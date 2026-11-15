// A page that isn't built yet. Later tickets replace these one by one.
export function PlaceholderPage({ title }: { title: string }) {
  return (
    <section>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-2 text-muted-foreground">Coming soon.</p>
    </section>
  )
}
