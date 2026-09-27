import { Link, useParams } from 'react-router-dom'

import { intelligenceApi, plannerApi, progressApi, subjectApi } from '@/api/endpoints'
import type { Analysis, Plan, Subject } from '@/api/types'
import { EmptyState, ErrorNote, ProgressBar, SectionHeader, Spinner, Stat } from '@/components/ui'
import {
  difficultyTone,
  formatDate,
  formatDayLabel,
  formatMinutes,
  isToday,
  kindTone,
  modeLabel,
  relativeDays,
  statusTone,
} from '@/lib/format'
import { useAsync } from '@/lib/useAsync'

export function SubjectPage() {
  const { subjectId } = useParams()
  const id = Number(subjectId)

  const subject = useAsync(() => subjectApi.get(id), [id])
  const analysis = useAsync<Analysis | null>(() => loadAnalysis(id), [id])
  const progress = useAsync(() => progressApi.subject(id), [id])
  const plan = useAsync<Plan | null>(() => loadPlan(id), [id])

  if (subject.loading || analysis.loading) return <Spinner label="Loading subject" />
  if (subject.error) return <ErrorNote message={subject.error} onRetry={subject.reload} />
  const data: Subject = subject.data!

  const intel = analysis.data?.intelligence
  const estimates = analysis.data?.estimates
  const todayBlocks = plan.data?.days.filter((day) => isToday(day.day)) ?? []

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="size-3 rounded-full" style={{ backgroundColor: data.color }} />
            <h1 className="text-2xl font-semibold text-slate-900">{data.name}</h1>
            {data.code ? <span className="badge bg-slate-200 text-slate-600">{data.code}</span> : null}
          </div>
          <p className="mt-1 text-sm text-slate-600">
            {modeLabel(data.study_mode)} · knowledge level {data.knowledge_level} ·{' '}
            {data.daily_minutes} min/day from {data.start_time}
          </p>
          <p className="mt-0.5 text-sm text-slate-600">
            {data.exam_date
              ? `Exam ${formatDate(data.exam_date)} (${relativeDays(data.days_to_exam)})`
              : 'No exam date set'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to={`/subjects/${id}/analysis`} className="btn-secondary">
            Analysis
          </Link>
          <Link to={`/subjects/${id}/upload`} className="btn-secondary">
            Add notes
          </Link>
          <Link to={`/subjects/${id}/planner`} className="btn-primary">
            Study plan
          </Link>
        </div>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Topics"
          value={data.topic_count}
          hint={`${data.document_count} source file(s)`}
        />
        <Stat
          label="Estimated workload"
          value={formatMinutes(estimates?.grand_total_minutes ?? data.total_minutes)}
          hint={estimates ? `${estimates.days_required} days at your budget` : 'Run analysis'}
        />
        <Stat
          label="Progress"
          value={`${Math.round(data.progress_percent)}%`}
          tone={data.progress_percent >= 80 ? 'good' : 'default'}
          hint={progress.data ? `${progress.data.topics_completed} of ${progress.data.topics_total} topics` : undefined}
        />
        <Stat
          label="Streak"
          value={`${progress.data?.streak_days ?? 0}d`}
          hint={progress.data?.streak_days ? 'Consecutive days with logged study' : 'Log progress to build a streak'}
        />
      </div>

      {!data.has_intelligence ? (
        <EmptyState
          title="No analysis yet"
          body="Upload your notes and run analysis to get topics, difficulty ratings and time estimates."
          action={
            <Link to={`/subjects/${id}/upload`} className="btn-primary">
              Upload notes
            </Link>
          }
        />
      ) : (
        <section className="space-y-3">
          <SectionHeader
            title="Topics"
            description="Scored deterministically from the notes: difficulty, time and exam relevance."
            actions={
              <Link to={`/subjects/${id}/analysis`} className="btn-ghost text-xs">
                See full analysis
              </Link>
            }
          />
          <div className="grid gap-3 md:grid-cols-2">
            {(intel?.topics ?? []).slice(0, 8).map((topic) => (
              <article key={topic.id} className="card">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs text-slate-500">{topic.module_title}</p>
                    <h3 className="text-sm font-semibold text-slate-900">{topic.title}</h3>
                  </div>
                  <span className={`badge ${difficultyTone(topic.difficulty)}`}>
                    {topic.difficulty}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-600">
                  <span>{formatMinutes(topic.estimated_minutes)} learn</span>
                  <span>{formatMinutes(topic.revision_minutes)} revise</span>
                  <span
                    className={`badge ${statusTone(topic.status)}`}
                    title="Progress on this topic"
                  >
                    {topic.status.replace('_', ' ')}
                  </span>
                </div>
                {topic.keywords.length > 0 ? (
                  <p className="mt-2 truncate text-xs text-slate-500">
                    {topic.keywords.slice(0, 6).join(' · ')}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      )}

      {todayBlocks.length > 0 ? (
        <section className="space-y-3">
          <SectionHeader title="Today" description="Your scheduled blocks for this subject." />
          <div className="card divide-y divide-slate-800">
            {todayBlocks[0].blocks.map((block) => (
              <div key={block.id} className="flex items-center gap-3 py-2 first:pt-0 last:pb-0">
                <span className="w-24 shrink-0 font-mono text-xs text-slate-500">
                  {block.start_time}–{block.end_time}
                </span>
                <span className={`w-20 shrink-0 text-xs font-semibold ${kindTone(block.kind)}`}>
                  {block.is_break ? 'break' : block.kind}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-slate-800">{block.title}</span>
                <span className="shrink-0 text-xs tabular-nums text-slate-500">
                  {block.minutes}m
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {plan.data ? (
        <section className="space-y-3">
          <SectionHeader
            title="Upcoming days"
            description={`${formatMinutes(plan.data.planned_minutes)} planned across the horizon.`}
            actions={
              <Link to={`/subjects/${id}/planner`} className="btn-ghost text-xs">
                Open planner
              </Link>
            }
          />
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {plan.data.days.slice(0, 8).map((day) => (
              <div key={day.day} className="card py-3">
                <p className="text-xs text-slate-500">{formatDayLabel(day.day)}</p>
                <p className="mt-0.5 text-sm font-semibold text-slate-900">
                  {day.is_rest_day ? 'Rest day' : formatMinutes(day.planned_minutes)}
                </p>
                <ProgressBar
                  className="mt-2"
                  value={day.completion_percent}
                  tone={day.completion_percent >= 100 ? 'emerald' : 'indigo'}
                />
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  )
}

/** A subject with no files has no analysis yet — that is a state, not an error. */
async function loadAnalysis(id: number): Promise<Analysis | null> {
  try {
    return await intelligenceApi.analysis(id)
  } catch (error) {
    if (error instanceof Error && /upload at least one/i.test(error.message)) return null
    throw error
  }
}

/** No plan yet is normal for a brand new subject. */
async function loadPlan(id: number): Promise<Plan | null> {
  try {
    return await plannerApi.get(id, 14)
  } catch (error) {
    if (error instanceof Error && /Generate one first/i.test(error.message)) return null
    throw error
  }
}
