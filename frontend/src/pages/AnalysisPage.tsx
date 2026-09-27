import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { intelligenceApi, progressApi } from '@/api/endpoints'
import type { Analysis, Topic } from '@/api/types'
import { EmptyState, ErrorNote, Pill, SectionHeader, Spinner, Stat } from '@/components/ui'
import { difficultyTone, formatDate, formatMinutes, statusTone } from '@/lib/format'
import { useAction, useAsync } from '@/lib/useAsync'

export function AnalysisPage() {
  const { subjectId } = useParams()
  const id = Number(subjectId)
  const analysis = useAsync<Analysis | null>(() => load(id), [id])
  const { busy, error, run } = useAction()
  const [useLlm, setUseLlm] = useState(true)
  const [openTopic, setOpenTopic] = useState<number | null>(null)
  const [includeRevision, setIncludeRevision] = useState(true)

  if (analysis.loading) return <Spinner label="Loading analysis" />
  if (analysis.error) return <ErrorNote message={analysis.error} onRetry={analysis.reload} />
  const data = analysis.data

  if (!data || !data.intelligence) {
    return (
      <div className="space-y-6">
        <SectionHeader title="Analysis" />
        <EmptyState
          title="No analysis yet"
          body="Upload notes for this subject, then run the analysis to extract topics, difficulty and time estimates."
          action={
            <div className="flex gap-2">
              <Link to={`/subjects/${id}/upload`} className="btn-secondary">
                Upload notes
              </Link>
              <button
                type="button"
                className="btn-primary"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const next = await intelligenceApi.analyze(id, useLlm)
                    if (data) analysis.setData({ ...data, intelligence: next })
                  })
                }
              >
                Run analysis
              </button>
            </div>
          }
        />
        {error ? <ErrorNote message={error} /> : null}
      </div>
    )
  }

  const intel = data.intelligence
  const estimates = data.estimates
  const sourceLabel =
    intel.source === 'heuristic'
      ? 'Deterministic structural analysis (offline)'
      : intel.source === 'gemini'
        ? 'Gemini content structuring + deterministic scoring'
        : 'Self-hosted model + deterministic scoring'

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <span
              className="size-3 rounded-full"
              style={{ backgroundColor: data.subject.color }}
            />
            <h1 className="text-2xl font-semibold text-slate-900">{data.subject.name}</h1>
          </div>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">{intel.summary}</p>
          <p className="mt-1 text-xs text-slate-500">
            {sourceLabel} · {formatDate(intel.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={useLlm}
              onChange={(e) => setUseLlm(e.target.checked)}
              className="accent-indigo-500"
            />
            Use Gemini for structuring
          </label>
          <button
            type="button"
            className="btn-secondary"
            disabled={busy}
          onClick={() =>
            void run(async () => {
              const next = await intelligenceApi.analyze(id, useLlm)
              if (data) analysis.setData({ ...data, intelligence: next })
            })
          }
          >
            {busy ? 'Analysing…' : 'Re-run analysis'}
          </button>
        </div>
      </header>

      {error ? <ErrorNote message={error} /> : null}
      {data.warnings.length > 0 ? (
        <div className="card border-amber-800/50 bg-amber-950/20 text-sm text-amber-200">
          <p className="font-semibold">Notes from extraction</p>
          <ul className="mt-1 list-disc pl-5 text-xs">
            {data.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Topics" value={intel.topic_count} />
        <Stat
          label="Learn time"
          value={formatMinutes(estimates?.total_minutes ?? intel.total_minutes)}
        />
        <Stat
          label="Revision time"
          value={formatMinutes(estimates?.revision_minutes ?? 0)}
        />
        <Stat
          label="Total workload"
          value={formatMinutes(estimates?.grand_total_minutes ?? intel.total_minutes)}
          tone="default"
        />
        <Stat
          label="Days needed"
          value={estimates?.days_required ?? '—'}
          tone={estimates?.feasible === false ? 'bad' : 'good'}
          hint={estimates?.feasible === false ? 'Over your budget' : 'At your daily budget'}
        />
      </div>

      {estimates ? (
        <section className="card space-y-3">
          <h2 className="h2">Feasibility</h2>
          <p className="text-sm text-slate-700">{estimates.message}</p>
          <div className="grid gap-3 sm:grid-cols-3">
            {(['easy', 'medium', 'hard'] as const).map((band) => {
              const count = estimates.breakdown[band]
              const minutes = estimates.breakdown[`minutes_${band}` as 'minutes_easy']
              return (
                <div key={band} className="rounded-lg border border-slate-300 p-3">
                  <div className="flex items-center justify-between">
                    <Pill className={difficultyTone(band)}>{band}</Pill>
                    <span className="text-xs text-slate-500">{count} topics</span>
                  </div>
                  <p className="mt-1.5 text-lg font-semibold text-slate-900 tabular-nums">
                    {formatMinutes(minutes)}
                  </p>
                </div>
              )
            })}
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs tracking-wide text-slate-500 uppercase">
                <th className="py-1.5">Module</th>
                <th className="py-1.5 text-right">Topics</th>
                <th className="py-1.5 text-right">Learn</th>
                <th className="py-1.5 text-right">Revise</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {estimates.per_module.map((module) => (
                <tr key={module.module}>
                  <td className="py-1.5 text-slate-700">{module.module}</td>
                  <td className="py-1.5 text-right tabular-nums text-slate-600">{module.topics}</td>
                  <td className="py-1.5 text-right tabular-nums text-slate-700">
                    {formatMinutes(module.minutes)}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-slate-600">
                    {formatMinutes(module.revision_minutes)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {intel.keywords.length > 0 || intel.learning_objectives.length > 0 ? (
        <section className="grid gap-4 lg:grid-cols-2">
          {intel.keywords.length > 0 ? (
            <div className="card">
              <h2 className="h2">Keywords</h2>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {intel.keywords.map((keyword) => (
                  <Pill key={keyword} className="bg-slate-200 text-slate-700">
                    {keyword}
                  </Pill>
                ))}
              </div>
            </div>
          ) : null}
          {intel.learning_objectives.length > 0 ? (
            <div className="card">
              <h2 className="h2">Learning objectives</h2>
              <ul className="mt-3 space-y-1.5 text-sm text-slate-700">
                {intel.learning_objectives.map((objective) => (
                  <li key={objective} className="flex gap-2">
                    <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-indigo-400" />
                    {objective}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="space-y-3">
        <SectionHeader
          title="Work packages"
          description={
            data.packages.length > 0
              ? `${data.packages.length} package(s), each capped at 90 minutes, split into 10–30 minute blocks.`
              : 'Generate packages to turn topics into schedulable work.'
          }
          actions={
            <>
              <label className="flex items-center gap-2 text-xs text-slate-600">
                <input
                  type="checkbox"
                  checked={includeRevision}
                  onChange={(e) => setIncludeRevision(e.target.checked)}
                  className="accent-indigo-500"
                />
                Include revision packages
              </label>
              <button
                type="button"
                className="btn-primary"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await intelligenceApi.generatePackages(id, includeRevision)
                    analysis.reload()
                  })
                }
              >
                {busy ? 'Generating…' : 'Generate packages'}
              </button>
            </>
          }
        />

        {data.packages.length === 0 ? (
          <EmptyState
            title="No work packages yet"
            body="Packages group topics into sessions of at most 90 minutes, which the planner then fits into your days."
          />
        ) : (
          <div className="space-y-2">
            {data.packages.map((pkg) => (
              <details key={pkg.id} className="card group py-0">
                <summary className="flex cursor-pointer flex-wrap items-center gap-3 py-3">
                  <span
                    className={`badge ${
                      pkg.type === 'revision'
                        ? 'bg-cyan-100 text-cyan-700'
                        : 'bg-indigo-100 text-indigo-700'
                    }`}
                  >
                    {pkg.type}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900">
                    {pkg.title}
                  </span>
                  <Pill className={difficultyTone(pkg.difficulty)}>{pkg.difficulty}</Pill>
                  <span className="w-20 text-right text-xs tabular-nums text-slate-600">
                    {formatMinutes(pkg.total_minutes)}
                  </span>
                  <span className="text-xs text-slate-500 group-open:hidden">
                    {pkg.units.length} block(s)
                  </span>
                </summary>
                <ul className="space-y-1.5 border-t border-slate-300 py-3">
                  {pkg.units.map((unit) => (
                    <li key={unit.id} className="flex flex-wrap items-baseline gap-2 text-sm">
                      <span className="badge bg-slate-200 text-slate-600">{unit.type}</span>
                      <span className="min-w-0 flex-1 text-slate-700">{unit.title}</span>
                      <span className="text-xs tabular-nums text-slate-500">{unit.minutes}m</span>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <SectionHeader
          title="Topics"
          description="Difficulty and time are computed from the notes. Click a topic to see the extracted knowledge."
        />
        <div className="space-y-2">
          {intel.topics.map((topic) => (
            <TopicRow
              key={topic.id}
              topic={topic}
              expanded={openTopic === topic.id}
              onToggle={() => setOpenTopic(openTopic === topic.id ? null : topic.id)}
              onComplete={async (event) => {
                await run(() =>
                  progressApi.record({
                    topic_id: topic.id,
                    event,
                    minutes_spent: topic.estimated_minutes,
                    confidence: event === 'completed' ? 0.8 : 0.3,
                  }),
                )
                analysis.reload()
              }}
            />
          ))}
        </div>
      </section>

      <div className="flex gap-2 border-t border-slate-300 pt-6">
        <Link to={`/subjects/${id}/planner`} className="btn-primary">
          Go to planner
        </Link>
        <Link to={`/subjects/${id}/upload`} className="btn-secondary">
          Add more notes
        </Link>
      </div>
    </div>
  )
}

function TopicRow({
  topic,
  expanded,
  onToggle,
  onComplete,
}: {
  topic: Topic
  expanded: boolean
  onToggle: () => void
  onComplete: (event: 'completed' | 'partial' | 'skipped') => Promise<void>
}) {
  return (
    <div className="card py-0">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-wrap items-center gap-3 py-3 text-left"
      >
        <Pill className={difficultyTone(topic.difficulty)}>{topic.difficulty}</Pill>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-slate-900">{topic.title}</span>
          <span className="text-xs text-slate-500">{topic.module_title}</span>
        </span>
        <span className="text-xs tabular-nums text-slate-600">
          {formatMinutes(topic.estimated_minutes)} + {formatMinutes(topic.revision_minutes)}
        </span>
        <span className="w-14 text-right text-xs tabular-nums text-slate-500">
          {(topic.importance * 100).toFixed(0)}%
        </span>
        <Pill className={statusTone(topic.status)}>{topic.status.replace('_', ' ')}</Pill>
        <span className="text-slate-500">{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded ? (
        <div className="space-y-4 border-t border-slate-300 py-3 text-sm">
          <div className="grid gap-4 md:grid-cols-2">
            <DetailList title="Learning objectives" items={topic.learning_objectives} />
            <DetailList title="Definitions" items={topic.definitions} />
            <DetailList title="Procedures" items={topic.procedures} />
            <DetailList title="Formulas" items={topic.formulas} mono />
            <DetailList title="Important facts" items={topic.important_facts} />
            <DetailList title="Subtopics" items={topic.subtopics} />
          </div>
          {topic.keywords.length > 0 ? (
            <div>
              <p className="label">Keywords</p>
              <div className="flex flex-wrap gap-1.5">
                {topic.keywords.map((keyword) => (
                  <Pill key={keyword} className="bg-slate-200 text-slate-700">
                    {keyword}
                  </Pill>
                ))}
              </div>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2 border-t border-slate-300 pt-3">
            <button type="button" className="btn-primary py-1 text-xs" onClick={() => void onComplete('completed')}>
              Mark complete
            </button>
            <button type="button" className="btn-secondary py-1 text-xs" onClick={() => void onComplete('partial')}>
              Partial
            </button>
            <button type="button" className="btn-ghost py-1 text-xs" onClick={() => void onComplete('skipped')}>
              Skip
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function DetailList({
  title,
  items,
  mono = false,
}: {
  title: string
  items: string[]
  mono?: boolean
}) {
  if (items.length === 0) return null
  return (
    <div>
      <p className="label">{title}</p>
      <ul className={`space-y-1 text-slate-700 ${mono ? 'font-mono text-xs' : ''}`}>
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-slate-600" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

async function load(id: number): Promise<Analysis | null> {
  try {
    return await intelligenceApi.analysis(id)
  } catch (error) {
    if (error instanceof Error && /upload at least one/i.test(error.message)) return null
    throw error
  }
}
