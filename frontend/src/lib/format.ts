/** Formatting helpers shared across screens. */

export function formatMinutes(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes <= 0) return '0m'
  if (minutes < 60) return `${Math.round(minutes)}m`
  const hours = Math.floor(minutes / 60)
  const rest = Math.round(minutes % 60)
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatDayLabel(value: string): string {
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}

export function todayIso(): string {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60_000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}

export function addDaysIso(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00`)
  date.setDate(date.getDate() + days)
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 10)
}

export function isPastDay(day: string): boolean {
  return day < todayIso()
}

export function isToday(day: string): boolean {
  return day === todayIso()
}

export function relativeDays(days: number | null | undefined): string {
  if (days === null || days === undefined) return 'No exam date'
  if (days < 0) return `${Math.abs(days)}d ago`
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return `in ${days} days`
}

export const WEEKDAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function isoWeekday(day: string): number {
  const date = new Date(`${day}T00:00:00`)
  return date.getDay() === 0 ? 7 : date.getDay()
}

export function difficultyTone(difficulty: string): string {
  switch (difficulty) {
    case 'easy':
      return 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30'
    case 'hard':
      return 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30'
    default:
      return 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30'
  }
}

export function statusTone(status: string): string {
  switch (status) {
    case 'done':
    case 'completed':
      return 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30'
    case 'partial':
    case 'in_progress':
      return 'bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/30'
    case 'missed':
    case 'skipped':
      return 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30'
    default:
      return 'bg-slate-300/40 text-slate-700 ring-1 ring-slate-600/40'
  }
}

export function kindTone(kind: string): string {
  switch (kind) {
    case 'learn':
      return 'text-indigo-300'
    case 'practice':
      return 'text-amber-300'
    case 'revision':
      return 'text-cyan-300'
    case 'teach':
      return 'text-emerald-300'
    case 'break':
      return 'text-slate-500'
    default:
      return 'text-slate-700'
  }
}

export function knowledgeLabel(level: string): string {
  return level.charAt(0).toUpperCase() + level.slice(1)
}

export function modeLabel(mode: string): string {
  return mode === 'fast_exam' ? 'Fast exam prep' : 'College pace'
}

export function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, value))
}
