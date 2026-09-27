import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '@/context/auth-context'

const NAV = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/subjects/new', label: 'New subject' },
  { to: '/upload', label: 'Upload' },
  { to: '/team', label: 'Team' },
  { to: '/planner', label: 'Planner' },
]

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-300/80 bg-slate-50/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <NavLink to="/dashboard" className="flex items-center gap-2">
            <img src="/logo.jpg" alt="Study Intelligence" className="size-8 rounded-md object-contain" />
            <span className="text-sm font-semibold tracking-tight">Study Intelligence</span>
          </NavLink>

          <nav className="flex flex-wrap items-center gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    isActive
                      ? 'bg-slate-200 text-slate-900'
                      : 'text-slate-600 hover:bg-slate-200/60 hover:text-slate-800'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <div className="text-right">
              <p className="text-sm font-medium text-slate-800">{user?.full_name}</p>
              <p className="text-xs text-slate-500">
                {user?.daily_minutes} min/day · from {user?.preferred_start_time}
              </p>
            </div>
            <button
              type="button"
              className="btn-ghost py-1.5 text-xs"
              onClick={() => {
                logout()
                navigate('/')
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-7xl px-4 pb-10 text-xs text-slate-600">
        Planning is fully deterministic — no language model decides your schedule, your time
        estimates or your workload split.
      </footer>
    </div>
  )
}
