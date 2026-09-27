import { createContext, useContext } from 'react'

import type { User } from '@/api/types'

export interface AuthValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (input: {
    email: string
    full_name: string
    password: string
    daily_minutes: number
    preferred_start_time: string
  }) => Promise<void>
  logout: () => void
  updateProfile: (body: {
    full_name?: string
    daily_minutes?: number
    preferred_start_time?: string
  }) => Promise<void>
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
