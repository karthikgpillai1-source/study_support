import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { plannerApi, progressApi, subjectApi } from '@/api/endpoints'
import type { Plan, Subject } from '@/api/types'
import { EmptyState, ErrorNote, ProgressBar, SectionHeader, Spinner, Stat } from '@/components/ui'
import {
  WEEKDAY_NAMES,
  formatDayLabel,
  formatMinutes,
  isPastDay,
  isToday,
  isoWeekday,
  kindTone,
  relativeDays,
  statusTone,
} from '@/lib/format'
import { useAction, useAsync } from '@/lib/useAsync'

export function PlannerPage() {
  const { subjectId } = useParams()
  const subjects = useAsync(() => subjectApi.list(), [])
  const [selected, setSelected] = useState<number | null>(subjectId ? Number(subjectId) : null)

  const all: Subject[] = subjects.data ?? []
  const activeId = selected ?? all[0]?.id ?? null

  if (subjects.loading) return <Spinner label="Loading subjects" />
  if (subjects.error) return <ErrorNote message={subjects.error} onRetry={subjects.reload} />

  if (all.length === 0) {
    return (
      <div className="space-y-6">
        <SectionHeader title="Planner" />
        <EmptyState
          title="Nothing to plan yet"
          body="Create a subject, upload notes, generate work packages, then come back here to build the schedule."
          action={
            <Link to="/subjects/new" className="btn-primary">
              Create a subject
            </Link>
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Planner"
        description="Deterministic scheduling: max 240 min/day, 10–30 min blocks, a 10 min break every two blocks."
      />

      <div className="card flex flex-wrap items-end gap-4">
        <div className="min-w-56 flex-1">
          <label className="label" htmlFor="subject">
            Subject
          </label>
          <select
            id="subject"
            className="field"
            value={activeId ?? ''}
            onChange={(e) => setSelected(Number(e.target.value))}
          >
            {all.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.name}
                {subject.exam_date ? ` — ${relativeDays(subject.days_to_exam)}` : ''}
              </option>
            ))}
          </select>
        </div>
        {activeId ? (
          <div className="flex flex-wrap gap-2">
            <Link to={`/subjects/${activeId}/analysis`} className="btn-ghost text-xs">
              Analysis
            </Link>
            <Link to={`/subjects/${activeId}/upload`} className="btn-ghost text-xs">
              Notes
            </Link>
          </div>
        ) : null}
      </div>

      {activeId ? <PlanWorkspace subjectId={activeId} subject={all.find((s) => s.id === activeId)!} /> : null}
    </div>
  )
}

function PlanWorkspace({ subjectId, subject }: { subjectId: number; subject: Subject }) {
  const [horizon, setHorizon] = useState(14)
  const [includeRevision, setIncludeRevision] = useState(true)
  const plan = useAsync<Plan | null>(() => loadPlan(subjectId), [subjectId])
  const week = useAsync(() => plannerApi.week(subjectId), [subjectId])
  const adaptive = useAsync(() => loadAdaptive(subjectId), [subjectId])
  const { busy, error, run } = useAction()

  async function regenerate(mode: 'rebuild' | 'keep_done') {
    await run(() =>
      plannerApi.generate(subjectId, {
        horizon_days: horizon,
        include_revision: includeRevision,
        mode,
      }),
    )
    plan.reload()
    week.reload()
    adaptive.reload()
  }

  async function switchMode(mode: string) {
    await run(() => plannerApi.setMode(subjectId, mode))
    plan.reload()
    adaptive.reload()
  }

  async function saveAvailability(next: { daily_minutes: number; start_time: string; rest_days: number[] }) {
    await run(() => plannerApi.setAvailability(subjectId, next))
    plan.reload()
    week.reload()
  }

  if (plan.loading) return <Spinner label="Loading plan" />
  if (plan.error) return <ErrorNote message={plan.error} onRetry={plan.reload} />

  const current = plan.data
  if (!current) {
    return (
      <div className="space-y-6">
        <EmptyState
          title="No plan for this subject"
          body="Generate work packages first, then build the schedule. The planner will fit everything into your available time up to the exam date."
          action={
            <div className="flex gap-2">
              <Link to={`/subjects/${subjectId}/analysis`} className="btn-secondary">
                Go to analysis
              </Link>
              <button
                type="button"
                className="btn-primary"
                disabled={busy}
                onClick={() => void regenerate('rebuild')}
              >
                {busy ? 'Generating…' : 'Generate plan'}
              </button>
            </div>
          }
        />
        {error ? <ErrorNote message={error} /> : null}
      </div>
    )
  }

  const unscheduled = (current.meta.unscheduled_unit_ids ?? []) as number[]

  return (
    <div className="space-y-6">
      {error ? <ErrorNote message={error} /> : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Planned" value={formatMinutes(current.planned_minutes)} />
        <Stat label="Daily budget" value={formatMinutes(current.daily_budget_minutes)} />
        <Stat
          label="Revision cadence"
          value={(current.meta.revision_offsets_days ?? []).map((d) => `+${d}d`).join(' ') || '—'}
          hint={current.study_mode === 'fast_exam' ? 'Fast exam prep' : 'College pace'}
        />
        <Stat
          label="Unscheduled"
          value={unscheduled.length}
          tone={unscheduled.length > 0 ? 'warn' : 'good'}
          hint={unscheduled.length > 0 ? 'Over capacity' : 'Everything fits'}
        />
      </div>

      {current.reason ? (
        <div
          className={`card text-sm ${
            unscheduled.length > 0
              ? 'border-amber-800/50 bg-amber-950/20 text-amber-200'
              : 'border-emerald-900/50 bg-emerald-950/20 text-emerald-200'
          }`}
        >
          {current.reason}
        </div>
      ) : null}

      <PlanControls
        horizon={horizon}
        setHorizon={setHorizon}
        includeRevision={includeRevision}
        setIncludeRevision={setIncludeRevision}
        studyMode={current.study_mode}
        busy={busy}
        onGenerate={() => void regenerate('rebuild')}
        onReplan={() => void regenerate('keep_done')}
        onSwitchMode={(mode) => void switchMode(mode)}
        subject={subject}
        onSaveAvailability={saveAvailability}
      />

      {adaptive.data ? <AdaptivePanel data={adaptive.data} /> : null}

      {week.data ? (
        <section className="card space-y-3">
          <SectionHeader
            title="This week"
            description={`${formatMinutes(week.data.planned_minutes)} planned · ${week.data.blocks_done}/${week.data.blocks_total} blocks done`}
          />
          <ProgressBar
            value={
              week.data.planned_minutes > 0
                ? (100 * week.data.completed_minutes) / week.data.planned_minutes
                : 0
            }
            tone="emerald"
          />
          <div className="grid gap-2 sm:grid-cols-7">
            {week.data.by_day.map((day) => (
              <div
                key={day.day}
                className={`rounded-lg border p-2 ${
                  day.is_rest_day ? 'border-slate-300 opacity-60' : 'border-slate-400'
                }`}
              >
                <p className="text-[11px] text-slate-500">{WEEKDAY_NAMES[isoWeekday(day.day) - 1]}</p>
                <p className="text-sm font-semibold text-slate-900 tabular-nums">
                  {day.is_rest_day ? 'Rest' : formatMinutes(day.planned_minutes)}
                </p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-slate-600">
            {week.data.by_kind.map((entry) => (
              <span key={entry.kind} className="capitalize">
                {entry.kind}: {formatMinutes(entry.minutes)}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      <section className="space-y-3">
        <SectionHeader
          title="Daily blocks"
          description={`${current.days.length} day(s) from ${formatDayLabel(current.generated_for)}`}
        />
        <div className="space-y-2">
          {current.days.map((day) => (
            <DayRow
              key={day.day}
              day={day}
              onToggleBlock={async (blockId, status) => {
                await run(() => plannerApi.updateBlock(blockId, { status }))
                plan.reload()
                week.reload()
              }}
              onLogTopic={async (topicId, event, minutes) => {
                await run(() => progressApi.record({ topic_id: topicId, event, minutes_spent: minutes }))
                adaptive.reload()
              }}
            />
          ))}
        </div>
      </section>
    </div>
  )
}

function PlanControls({
  horizon,
  setHorizon,
  includeRevision,
  setIncludeRevision,
  studyMode,
  busy,
  onGenerate,
  onReplan,
  onSwitchMode,
  subject,
  onSaveAvailability,
}: {
  horizon: number
  setHorizon: (value: number) => void
  includeRevision: boolean
  setIncludeRevision: (value: boolean) => void
  studyMode: string
  busy: boolean
  onGenerate: () => void
  onReplan: () => void
  onSwitchMode: (mode: string) => void
  subject: Subject
  onSaveAvailability: (next: {
    daily_minutes: number
    start_time: string
    rest_days: number[]
  }) => Promise<void>
}) {
  const [minutes, setMinutes] = useState(subject.daily_minutes)
  const [start, setStart] = useState(subject.start_time)
  const [rest, setRest] = useState<number[]>(subject.rest_days)

  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label className="label" htmlFor="horizon">
            Horizon (days)
          </label>
          <input
            id="horizon"
            type="number"
            min={1}
            max={90}
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
            className="field w-28"
          />
        </div>
        <div>
          <label className="label" htmlFor="mode">
            Study mode
          </label>
          <select
            id="mode"
            className="field w-48"
            value={studyMode}
            onChange={(e) => onSwitchMode(e.target.value)}
            disabled={busy}
          >
            <option value="fast_exam">Fast exam preparation</option>
            <option value="college_pace">Follow college pace</option>
          </select>
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={includeRevision}
            onChange={(e) => setIncludeRevision(e.target.checked)}
            className="accent-indigo-500"
          />
          Include revision passes
        </label>
        <div className="ml-auto flex gap-2">
          <button type="button" className="btn-secondary" disabled={busy} onClick={onReplan}>
            Re-plan (keep history)
          </button>
          <button type="button" className="btn-primary" disabled={busy} onClick={onGenerate}>
            {busy ? 'Working…' : 'Generate plan'}
          </button>
        </div>
      </div>

      <details className="border-t border-slate-300 pt-3">
        <summary className="cursor-pointer text-sm font-semibold text-slate-800">
          My availability
        </summary>
        <div className="mt-3 flex flex-wrap items-end gap-4">
          <div>
            <label className="label" htmlFor="avail_minutes">
              Minutes per day
            </label>
            <div className="flex items-center gap-2">
              <input
                id="avail_minutes"
                type="range"
                min={15}
                max={240}
                step={15}
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value))}
                className="w-40 accent-indigo-500"
              />
              <span className="w-12 text-sm tabular-nums text-slate-700">{minutes}m</span>
            </div>
          </div>
          <div>
            <label className="label" htmlFor="avail_start">
              Start time
            </label>
            <input
              id="avail_start"
              type="time"
              className="field w-32"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>
          <div className="flex-1">
            <p className="label">Rest days</p>
            <div className="flex flex-wrap gap-1.5">
              {WEEKDAY_NAMES.map((label, index) => {
                const day = index + 1
                const active = rest.includes(day)
                return (
                  <button
                    key={day}
                    type="button"
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                      active ? 'bg-[var(--primary)] text-[var(--bg-main)]' : 'border border-slate-400 text-slate-700'
                    }`}
                    onClick={() =>
                      setRest(active ? rest.filter((d) => d !== day) : [...rest, day].sort())
                    }
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </div>
          <button
            type="button"
            className="btn-secondary"
            disabled={busy}
            onClick={() => void onSaveAvailability({ daily_minutes: minutes, start_time: start, rest_days: rest })}
          >
            Save &amp; re-plan
          </button>
        </div>
      </details>
    </div>
  )
}

function AdaptivePanel({ data }: { data: import('@/api/types').AdaptiveReport }) {
  const tone =
    data.status === 'behind'
      ? 'border-amber-800/50 bg-amber-950/20 text-amber-200'
      : data.status === 'ahead'
        ? 'border-emerald-900/50 bg-emerald-950/20 text-emerald-200'
        : 'border-slate-300 bg-slate-100/40 text-slate-700'

  return (
    <div className={`card space-y-2 ${tone}`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="badge bg-black/20 uppercase">{data.status.replace('_', ' ')}</span>
        <p className="text-sm">{data.summary}</p>
      </div>
      {data.actions.length > 0 ? (
        <ul className="space-y-2 pt-1">
          {data.actions.map((action) => (
            <li key={action.kind} className="rounded-lg bg-black/20 p-3 text-sm">
              <p className="font-semibold">{action.label}</p>
              <p className="mt-0.5 text-xs opacity-90">{action.rationale}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function DayRow({
  day,
  onToggleBlock,
  onLogTopic,
}: {
  day: import('@/api/types').DayPlan
  onToggleBlock: (blockId: number, status: string) => Promise<void>
  onLogTopic: (topicId: number, event: 'completed' | 'partial' | 'skipped', minutes: number) => Promise<void>
}) {
  const past = isPastDay(day.day)
  const today = isToday(day.day)

  return (
    <div
      className={`card py-0 ${
        today ? 'border-indigo-500/50 ring-1 ring-indigo-500/20' : ''
      } ${past ? 'opacity-90' : ''}`}
    >
      <div className="flex flex-wrap items-center gap-3 py-3">
        <div className="w-40 shrink-0">
          <p className="text-sm font-semibold text-slate-900">{formatDayLabel(day.day)}</p>
          <p className="text-xs text-slate-500">
            {day.is_rest_day ? 'Rest day' : `${formatMinutes(day.planned_minutes)} of ${day.budget_minutes}m`}
          </p>
        </div>
        {day.planned_minutes > 0 ? (
          <div className="w-28 shrink-0">
            <ProgressBar
              value={day.completion_percent}
              tone={day.completion_percent >= 100 ? 'emerald' : 'indigo'}
            />
            <p className="mt-1 text-[11px] text-slate-500 tabular-nums">
              {Math.round(day.completion_percent)}%
            </p>
          </div>
        ) : null}
        <span className="ml-auto text-xs text-slate-500">
          {day.blocks.filter((b) => !b.is_break).length} block(s)
        </span>
      </div>

      {day.blocks.length > 0 ? (
        <ul className="divide-y divide-slate-800/70 border-t border-slate-300">
          {day.blocks.map((block) => (
            <li key={block.id} className="flex flex-wrap items-center gap-3 py-2">
              <span className="w-24 shrink-0 font-mono text-xs text-slate-500">
                {block.start_time}–{block.end_time}
              </span>
              <span className={`w-16 shrink-0 text-xs font-semibold ${kindTone(block.kind)}`}>
                {block.is_break ? 'break' : block.kind}
              </span>
              <span
                className={`min-w-0 flex-1 truncate text-sm ${
                  block.is_break ? 'text-slate-500 italic' : 'text-slate-800'
                }`}
              >
                {block.title}
                {block.note ? <span className="ml-1 text-xs text-slate-500">({block.note})</span> : null}
              </span>
              <span className="w-10 shrink-0 text-right text-xs tabular-nums text-slate-500">
                {block.minutes}m
              </span>
              {block.is_break ? null : (
                <span className="flex shrink-0 gap-1">
                  <button
                    type="button"
                    title="Mark done"
                    className="rounded-md px-1.5 py-0.5 text-xs text-emerald-300 hover:bg-emerald-500/10"
                    onClick={() => {
                      if (block.topic_id) {
                        void onLogTopic(block.topic_id, 'completed', block.minutes)
                      } else {
                        void onToggleBlock(block.id, 'done')
                      }
                    }}
                  >
                    ✓
                  </button>
                  <button
                    type="button"
                    title="Mark partial"
                    className="rounded-md px-1.5 py-0.5 text-xs text-amber-300 hover:bg-amber-500/10"
                    onClick={() => void onToggleBlock(block.id, 'partial')}
                  >
                    ~
                  </button>
                  <button
                    type="button"
                    title="Mark missed"
                    className="rounded-md px-1.5 py-0.5 text-xs text-rose-300 hover:bg-rose-500/10"
                    onClick={() => void onToggleBlock(block.id, 'missed')}
                  >
                    ✕
                  </button>
                </span>
              )}
              {block.status !== 'planned' ? (
                <span className={`badge ${statusTone(block.status)}`}>{block.status}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

async function loadPlan(id: number): Promise<Plan | null> {
  try {
    return await plannerApi.get(id, 14)
  } catch (error) {
    if (error instanceof Error && /Generate one first/i.test(error.message)) return null
    throw error
  }
}

async function loadAdaptive(id: number) {
  try {
    return await plannerApi.adaptive(id)
  } catch (error) {
    if (error instanceof Error && /Generate a plan/i.test(error.message)) return null
    throw error
  }
}
