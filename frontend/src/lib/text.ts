// Small text helpers. SMA-32.

/** The first few words, with "…" when there were more (like the backend's fallback title). */
export function firstWords(text: string, count = 6): string {
  const words = text.split(/\s+/).filter(Boolean)
  const start = words.slice(0, count).join(' ')
  return words.length > count ? `${start}…` : start
}
