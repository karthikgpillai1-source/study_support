import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { authApi } from '@/api/endpoints'
import { ApiError, getToken, setToken } from '@/api/client'
import type { User } from '@/api/types'
import { AuthContext } from './auth-context'
import type { AuthValue } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    if (!getToken()) {
      setLoading(false)
      return
    }
    authApi
      .me()
      .then((me) => {
        if (!cancelled) setUser(me)
      })
      .catch((error: unknown) => {
        if (!cancelled && error instanceof ApiError && error.isAuthError) setToken(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const result = await authApi.login({ email, password })
    setToken(result.access_token)
    setUser(result.user)
  }, [])

  const register = useCallback(
    async (input: {
      email: string
      full_name: string
      password: string
      daily_minutes: number
      preferred_start_time: string
    }) => {
      const result = await authApi.register(input)
      setToken(result.access_token)
      setUser(result.user)
    },
    [],
  )

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const updateProfile = useCallback(
    async (body: { full_name?: string; daily_minutes?: number; preferred_start_time?: string }) => {
      setUser(await authApi.updateProfile(body))
    },
    [],
  )

  const value = useMemo<AuthValue>(
    () => ({ user, loading, login, register, logout, updateProfile }),
    [user, loading, login, register, logout, updateProfile],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
