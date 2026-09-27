import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Minimal data-fetching hook: run an async loader, expose loading/error/data,
 * and let the caller refetch. No external dependency needed for this scale.
 */
export function useAsync<T>(
  loader: () => Promise<T>,
  deps: unknown[] = [],
): {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
  setData: (value: T) => void
} {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    loaderRef
      .current()
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'Something went wrong')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  return { data, error, loading, reload, setData }
}

/** Track a one-shot async action (save, generate, accept) with its own status. */
export function useAction(): {
  busy: boolean
  error: string | null
  run: <T>(action: () => Promise<T>) => Promise<T | null>
  reset: () => void
} {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | null> => {
    setBusy(true)
    setError(null)
    try {
      return await action()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Something went wrong')
      return null
    } finally {
      setBusy(false)
    }
  }, [])

  return { busy, error, run, reset: () => setError(null) }
}
