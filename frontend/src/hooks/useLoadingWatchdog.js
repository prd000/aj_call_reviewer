import { useEffect } from 'react'

const DEFAULT_TIMEOUT_MS = 15_000

export function useLoadingWatchdog(isLoading, setLoading, options = {}) {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, onTimeout, label = 'loading' } = options

  useEffect(() => {
    if (!isLoading) return
    const id = setTimeout(() => {
      console.error(
        `[useLoadingWatchdog] ${label} exceeded ${timeoutMs}ms — auto-clearing`
      )
      setLoading(false)
      if (onTimeout) onTimeout()
    }, timeoutMs)
    return () => clearTimeout(id)
  }, [isLoading, setLoading, timeoutMs, onTimeout, label])
}
