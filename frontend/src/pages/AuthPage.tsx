import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { ErrorNote } from '@/components/ui'
import { useAuth } from '@/context/auth-context'
import { useAction } from '@/lib/useAsync'

const LEVELS = [
  { value: 'novice', label: 'Novice', hint: 'New to this subject' },
  { value: 'beginner', label: 'Beginner', hint: 'Recall the basics' },
  { value: 'intermediate', label: 'Intermediate', hint: 'Comfortable fundamentals' },
  { value: 'advanced', label: 'Advanced', hint: 'Strong, need depth' },
  { value: 'expert', label: 'Expert', hint: 'Near mastery' },
]

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const { busy, error, run } = useAction()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [dailyMinutes, setDailyMinutes] = useState(120)
  const [startTime, setStartTime] = useState('18:00')

  const isRegister = mode === 'register'

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const result = await run(async () => {
      if (isRegister) {
        await register({
          email,
          full_name: fullName,
          password,
          daily_minutes: dailyMinutes,
          preferred_start_time: startTime,
        })
      } else {
        await login(email, password)
      }
    })
    if (result !== null) {
      setTimeout(() => navigate('/dashboard'), 0)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between border-r border-slate-300/70 p-10 lg:flex">
        <Link to="/" className="flex items-center gap-2">
          <img src="/logo.jpg" alt="Study Intelligence" className="size-8 rounded-md object-contain" />
          <span className="text-sm font-semibold">Study Intelligence</span>
        </Link>
        <div>
          <h2 className="max-w-md text-3xl font-bold tracking-tight text-slate-900">
            Your notes in. A plan you can follow out.
          </h2>
          <p className="mt-3 max-w-md text-slate-600">
            The planner is deterministic Python: 240 minutes a day, 10–30 minute blocks, a break
            every two blocks, and packages capped at 90 minutes.
          </p>
        </div>
        <p className="text-xs text-slate-600">No chatbot. No generic assistant.</p>
      </div>

      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-semibold text-slate-900">
            {isRegister ? 'Create your account' : 'Sign in'}
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            {isRegister
              ? 'Set your default availability. You can override it per subject.'
              : 'Welcome back.'}
          </p>

          <form className="mt-6 space-y-4" onSubmit={onSubmit}>
            {isRegister ? (
              <div>
                <label className="label" htmlFor="full_name">
                  Full name
                </label>
                <input
                  id="full_name"
                  className="field"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                  minLength={2}
                  autoComplete="name"
                />
              </div>
            ) : null}

            <div>
              <label className="label" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                className="field"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>

            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                className="field"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={isRegister ? 8 : undefined}
                autoComplete={isRegister ? 'new-password' : 'current-password'}
              />
              {isRegister ? (
                <p className="mt-1 text-xs text-slate-500">At least 8 characters.</p>
              ) : null}
            </div>

            {isRegister ? (
              <>
                <div>
                  <label className="label" htmlFor="daily_minutes">
                    Default study time per day
                  </label>
                  <div className="flex items-center gap-3">
                    <input
                      id="daily_minutes"
                      type="range"
                      min={15}
                      max={240}
                      step={15}
                      value={dailyMinutes}
                      onChange={(e) => setDailyMinutes(Number(e.target.value))}
                      className="flex-1 accent-indigo-500"
                    />
                    <span className="w-16 text-right text-sm tabular-nums text-slate-700">
                      {dailyMinutes}m
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">The hard cap is 240 minutes a day.</p>
                </div>

                <div>
                  <label className="label" htmlFor="start_time">
                    Usual study start time
                  </label>
                  <input
                    id="start_time"
                    type="time"
                    className="field"
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                    required
                  />
                </div>
              </>
            ) : null}

            {error ? <ErrorNote message={error} /> : null}

            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in'}
            </button>
          </form>

          <p className="mt-6 text-sm text-slate-600">
            {isRegister ? 'Already have an account? ' : 'No account yet? '}
            <Link className="link" to={isRegister ? '/login' : '/register'}>
              {isRegister ? 'Sign in' : 'Create one'}
            </Link>
          </p>

          {isRegister ? (
            <div className="mt-8 rounded-lg border border-slate-300 bg-slate-100/40 p-4">
              <p className="text-xs font-semibold tracking-wide text-slate-600 uppercase">
                Knowledge levels
              </p>
              <ul className="mt-2 space-y-1 text-xs text-slate-500">
                {LEVELS.map((level) => (
                  <li key={level.value}>
                    <span className="text-slate-700">{level.label}</span> — {level.hint}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
