import { Link } from 'react-router-dom'

import { progressApi, subjectApi } from '@/api/endpoints'
import type { Dashboard } from '@/api/types'
import { EmptyState, ErrorNote, ProgressBar, SectionHeader, Spinner, Stat } from '@/components/ui'
import {
  formatDate,
  formatDayLabel,
  formatMinutes,
  knowledgeLabel,
  kindTone,
  modeLabel,
  relativeDays,
  statusTone,
} from '@/lib/format'
import { useAsync } from '@/lib/useAsync'

export function DashboardPage() {
  const dashboard = useAsync<Dashboard | null>(() => loadDashboard(), [])
  const subjects = useAsync(() => subjectApi.list(), [])

  if (dashboard.loading) return <Spinner label="Loading your dashboard" />
  if (dashboard.error) return <ErrorNote message={dashboard.error} onRetry={dashboard.reload} />
  const data = dashboard.data

  if (!data || data.subjects.length === 0) {
    return (
      <div className="space-y-6">
        <SectionHeader title="Dashboard" />
        <EmptyState
          title="No subjects yet"
          body="Create your first subject, upload your notes, and the platform will build the study intelligence and a plan from them."
          action={
            <Link to="/subjects/new" className="btn-primary">
              Create a subject
            </Link>
          }
        />
      </div>
    )
  }

  const todayMinutes = data.totals.minutes_today

  return (
    <div className="space-y-8">
      <SectionHeader
        title="Dashboard"
        description={`${data.totals.subjects} subject(s) · ${data.totals.topics} topics tracked`}
        actions={
          <>
            <Link to="/upload" className="btn-secondary">
              Upload notes
            </Link>
            <Link to="/subjects/new" className="btn-primary">
              New subject
            </Link>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Planned today"
          value={formatMinutes(todayMinutes)}
          hint={`${data.totals.blocks_today} block(s)`}
          tone={todayMinutes > 0 ? 'default' : 'warn'}
        />
        <Stat
          label="Total workload"
          value={formatMinutes(data.totals.minutes_planned)}
          hint="Across all subjects"
        />
        <Stat
          label="Completed"
          value={formatMinutes(data.totals.minutes_completed)}
          tone="good"
          hint="Logged study time"
        />
        <Stat
          label="Next deadline"
          value={
            data.upcoming_deadlines[0]
              ? relativeDays(data.upcoming_deadlines[0].days_left)
              : 'None set'
          }
          hint={data.upcoming_deadlines[0]?.name}
          tone={data.upcoming_deadlines[0]?.feasible === false ? 'bad' : 'default'}
        />
      </div>

      <section className="space-y-3">
        <SectionHeader title="Today's plan" />
        {data.today.length === 0 ? (
          <EmptyState
            title="Nothing scheduled today"
            body="Generate a plan for a subject and today's blocks will appear here."
            action={
              <Link to="/planner" className="btn-primary">
                Open planner
              </Link>
            }
          />
        ) : (
          <div className="card divide-y divide-slate-800">
            {data.today.map((block) => (
              <div key={block.id} className="flex flex-wrap items-center gap-3 py-2.5 first:pt-0 last:pb-0">
                <span className="w-24 shrink-0 font-mono text-xs text-slate-500">
                  {block.start_time}–{block.end_time}
                </span>
                <span
                  className="size-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: block.color }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-slate-800">{block.title}</span>
                  <span className="text-xs text-slate-500">{block.subject_name}</span>
                </span>
                <span className={`badge ${statusTone(block.status)}`}>{block.status}</span>
                <span className={`w-16 shrink-0 text-right text-xs font-semibold ${kindTone(block.kind)}`}>
                  {block.kind}
                </span>
                <span className="w-12 shrink-0 text-right text-xs tabular-nums text-slate-500">
                  {block.minutes}m
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <SectionHeader title="Your subjects" />
        <div className="grid gap-4 md:grid-cols-2">
          {data.subjects.map((subject) => (
            <article key={subject.id} className="card space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className="size-2.5 rounded-full"
                      style={{ backgroundColor: subject.color }}
                    />
                    <Link
                      to={`/subjects/${subject.id}`}
                      className="truncate text-sm font-semibold text-slate-900 hover:text-slate-900"
                    >
                      {subject.name}
                    </Link>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {modeLabel(subject.study_mode)} · {knowledgeLabel(subject.knowledge_level)}
                  </p>
                </div>
                {subject.exam_date ? (
                  <span
                    className={`badge ${
                      (subject.days_to_exam ?? 99) <= 7
                        ? 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30'
                        : 'bg-slate-200 text-slate-700'
                    }`}
                  >
                    {relativeDays(subject.days_to_exam)}
                  </span>
                ) : null}
              </div>

              <div>
                <div className="flex items-center justify-between text-xs text-slate-600">
                  <span>{Math.round(subject.progress_percent)}% complete</span>
                  <span className="tabular-nums">
                    {subject.topic_count} topics · {formatMinutes(subject.total_minutes)}
                  </span>
                </div>
                <ProgressBar
                  className="mt-1.5"
                  value={subject.progress_percent}
                  tone={subject.progress_percent >= 80 ? 'emerald' : 'indigo'}
                />
              </div>

              <div className="flex flex-wrap gap-1.5 text-xs">
                {subject.has_intelligence ? (
                  <span className="badge bg-emerald-500/10 text-emerald-300">analysed</span>
                ) : (
                  <span className="badge bg-amber-500/10 text-amber-300">needs analysis</span>
                )}
                {subject.has_active_plan ? (
                  <span className="badge bg-[var(--bg-elevated)] text-[var(--primary)]">planned</span>
                ) : (
                  <span className="badge bg-slate-200 text-slate-600">no plan</span>
                )}
                {subject.team_id ? (
                  <span className="badge bg-cyan-500/10 text-cyan-300">team</span>
                ) : null}
              </div>

              <div className="flex flex-wrap gap-2 pt-1">
                <Link to={`/subjects/${subject.id}/analysis`} className="btn-ghost px-2 py-1 text-xs">
                  Analysis
                </Link>
                <Link to={`/subjects/${subject.id}/upload`} className="btn-ghost px-2 py-1 text-xs">
                  Notes
                </Link>
                <Link to={`/subjects/${subject.id}/planner`} className="btn-ghost px-2 py-1 text-xs">
                  Planner
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      {data.upcoming_deadlines.length > 0 ? (
        <section className="space-y-3">
          <SectionHeader title="Upcoming deadlines" />
          <div className="card divide-y divide-slate-800">
            {data.upcoming_deadlines.map((deadline) => (
              <div key={deadline.subject_id} className="flex flex-wrap items-center gap-3 py-2.5">
                <Link
                  to={`/subjects/${deadline.subject_id}`}
                  className="min-w-0 flex-1 truncate text-sm text-slate-800 hover:text-slate-900"
                >
                  {deadline.name}
                </Link>
                <span className="text-xs text-slate-500">
                  {formatDate(deadline.exam_date)}
                </span>
                <span className="badge bg-slate-200 text-slate-700">
                  {relativeDays(deadline.days_left)}
                </span>
                <span
                  className={`badge ${
                    deadline.feasible
                      ? 'bg-emerald-500/10 text-emerald-300'
                      : 'bg-rose-500/10 text-rose-300'
                  }`}
                >
                  {deadline.feasible ? 'on track' : 'tight'}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {data.plans.length > 0 ? (
        <section className="space-y-3">
          <SectionHeader title="Generated plans" />
          <div className="card divide-y divide-slate-800">
            {data.plans.map((plan) => (
              <div key={plan.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <span
                  className="size-2.5 rounded-full"
                  style={{ backgroundColor: plan.color }}
                />
                <Link
                  to={`/subjects/${plan.subject_id}/planner`}
                  className="min-w-0 flex-1 truncate text-sm text-slate-800 hover:text-slate-900"
                >
                  {plan.subject_name}
                </Link>
                <span className="text-xs text-slate-500">
                  from {formatDayLabel(plan.generated_for)} · {plan.horizon_days}d horizon
                </span>
                <span className="text-xs tabular-nums text-slate-600">
                  {formatMinutes(plan.planned_minutes)}
                </span>
                {plan.unscheduled > 0 ? (
                  <span className="badge bg-amber-500/10 text-amber-300">
                    {plan.unscheduled} unscheduled
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {data.team ? (
        <section className="card flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-slate-900">{data.team.name}</p>
            <p className="text-xs text-slate-500">
              {data.team.members} member(s) · {data.team.subjects} shared subject(s) · you are{' '}
              {data.team.role} · code{' '}
              <span className="font-mono text-slate-600">{data.team.join_code}</span>
            </p>
          </div>
          <Link to="/team" className="btn-secondary">
            Open team
          </Link>
        </section>
      ) : null}

      {subjects.error ? <ErrorNote message={subjects.error} /> : null}
    </div>
  )
}

async function loadDashboard(): Promise<Dashboard | null> {
  return progressApi.dashboard()
}
