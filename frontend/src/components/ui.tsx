import type { ReactNode } from 'react'

import { clampPercent } from '@/lib/format'

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 text-slate-600">
      <span
        aria-hidden
        className="size-4 animate-spin rounded-full border-2 border-slate-400 border-t-indigo-400"
      />
      <span className="text-sm">{label}…</span>
    </div>
  )
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
      <span>{message}</span>
      {onRetry ? (
        <button type="button" className="btn-secondary py-1 text-xs" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: ReactNode
}) {
  return (
    <div className="card flex flex-col items-center gap-3 border-dashed text-center">
      <h3 className="text-base font-semibold text-slate-800">{title}</h3>
      <p className="max-w-md text-sm text-slate-600">{body}</p>
      {action}
    </div>
  )
}

export function ProgressBar({
  value,
  tone = 'indigo',
  className = '',
}: {
  value: number
  tone?: 'indigo' | 'emerald' | 'rose' | 'amber'
  className?: string
}) {
  const percent = clampPercent(value)
  const colors = {
    indigo: 'bg-indigo-400',
    emerald: 'bg-emerald-400',
    rose: 'bg-rose-400',
    amber: 'bg-amber-400',
  }
  return (
    <div
      className={`h-1.5 w-full overflow-hidden rounded-full bg-slate-200 ${className}`}
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={`h-full rounded-full transition-[width] ${colors[tone]}`}
        style={{ width: `${percent}%` }}
      />
    </div>
  )
}

export function Stat({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string
  value: ReactNode
  hint?: string
  tone?: 'default' | 'good' | 'warn' | 'bad'
}) {
  const toneClass = {
    default: 'text-slate-900',
    good: 'text-emerald-300',
    warn: 'text-amber-300',
    bad: 'text-rose-300',
  }
  return (
    <div className="card">
      <p className="text-xs font-semibold tracking-wide text-slate-600 uppercase">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${toneClass[tone]}`}>{value}</p>
      {hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
    </div>
  )
}

export function SectionHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="h2">{title}</h2>
        {description ? <p className="mt-0.5 text-sm text-slate-600">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  )
}

export function Pill({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <span className={`badge ${className}`}>{children}</span>
}
