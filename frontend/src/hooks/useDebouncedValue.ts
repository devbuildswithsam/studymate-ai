// The value, but only once it has stopped changing for `delayMs`. SMA-32.
// Used for search-as-you-type: one request after a pause, not one per key press.
import { useEffect, useState } from 'react'

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer) // typed again before the delay: start waiting again
  }, [value, delayMs])
  return debounced
}
