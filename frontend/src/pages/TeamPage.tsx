import { useState } from 'react'
import { Link } from 'react-router-dom'

import { subjectApi, teamApi } from '@/api/endpoints'
import type { KnowledgeMatrix, PeerRecommendations, Subject, Team, TeamSplit } from '@/api/types'
import { EmptyState, ErrorNote, Pill, SectionHeader, Spinner, Stat } from '@/components/ui'
import { clampPercent, formatMinutes } from '@/lib/format'
import { useAction, useAsync } from '@/lib/useAsync'

export function TeamPage() {
  const teams = useAsync(() => teamApi.list(), [])
  const { busy, error, run } = useAction()
  const [name, setName] = useState('')
  const [joinCode, setJoinCode] = useState('')

  if (teams.loading) return <Spinner label="Loading your teams" />
  if (teams.error) return <ErrorNote message={teams.error} onRetry={teams.reload} />
  const all: Team[] = teams.data ?? []

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Study team"
        description="Share notes and a plan, then get work-distribution suggestions. Nothing is ever assigned automatically."
      />

      {error ? <ErrorNote message={error} /> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <form
          className="card space-y-3"
          onSubmit={async (event) => {
            event.preventDefault()
            const created = await run(() => teamApi.create(name))
            if (created) {
              setName('')
              teams.reload()
            }
          }}
        >
          <h2 className="h2">Create a team</h2>
          <div>
            <label className="label" htmlFor="team_name">
              Team name
            </label>
            <input
              id="team_name"
              className="field"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="CS Study Group"
              required
              minLength={2}
            />
          </div>
          <button type="submit" className="btn-primary" disabled={busy || !name.trim()}>
            {busy ? 'Creating…' : 'Create team'}
          </button>
        </form>

        <form
          className="card space-y-3"
          onSubmit={async (event) => {
            event.preventDefault()
            const joined = await run(() => teamApi.join(joinCode))
            if (joined) {
              setJoinCode('')
              teams.reload()
            }
          }}
        >
          <h2 className="h2">Join a team</h2>
          <div>
            <label className="label" htmlFor="join_code">
              Join code
            </label>
            <input
              id="join_code"
              className="field font-mono uppercase"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
              placeholder="ABC123"
              required
              maxLength={12}
            />
          </div>
          <button type="submit" className="btn-primary" disabled={busy || joinCode.length < 4}>
            {busy ? 'Joining…' : 'Join team'}
          </button>
        </form>
      </div>

      {all.length === 0 ? (
        <EmptyState
          title="You are studying solo"
          body="Create a team to share notes, split the syllabus and see a knowledge matrix across members. Solo subjects work fine too."
        />
      ) : (
        all.map((team) => <TeamDetail key={team.id} team={team} onChanged={teams.reload} />)
      )}
    </div>
  )
}

function TeamDetail({ team, onChanged }: { team: Team; onChanged: () => void }) {
  const subjects = useAsync<Subject[] | null>(() => loadTeamSubjects(team.id), [team.id])
  const [selected, setSelected] = useState<number | null>(null)
  const { busy, error, run } = useAction()

  const list: Subject[] = subjects.data ?? []
  const activeId = selected ?? list[0]?.id ?? null

  return (
    <section className="space-y-4">
      <div className="card flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="h2">{team.name}</h2>
          <p className="mt-0.5 text-sm text-slate-600">
            {team.members.length} member(s) · {team.subjects.length} shared subject(s)
          </p>
          <p className="mt-2 text-sm text-slate-700">
            Join code:{' '}
            <span className="rounded-md bg-slate-200 px-2 py-0.5 font-mono text-indigo-300">
              {team.join_code}
            </span>
          </p>
        </div>
        <div className="flex gap-2">
          <Link to={`/subjects/new?team=${team.id}`} className="btn-primary">
            Add shared subject
          </Link>
          <button
            type="button"
            className="btn-danger"
            disabled={busy}
            onClick={async () => {
              if (team.owner_id === team.members.find((m) => m.role === 'owner')?.user_id) {
                // handled by the API; the confirm is enough for now
              }
              const result = await run(() =>
                team.owner_id ? teamApi.leave(team.id) : teamApi.remove(team.id),
              )
              if (result !== null) onChanged()
            }}
          >
            {team.members.some((m) => m.role === 'owner') ? 'Leave team' : 'Delete team'}
          </button>
        </div>
      </div>

      {error ? <ErrorNote message={error} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {team.members.map((member) => (
          <div key={member.user_id} className="card py-3">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-sm font-medium text-slate-900">{member.full_name}</p>
              <Pill
                className={
                  member.role === 'owner'
                    ? 'bg-indigo-100 text-indigo-700'
                    : 'bg-slate-200 text-slate-600'
                }
              >
                {member.role}
              </Pill>
            </div>
            <p className="truncate text-xs text-slate-500">{member.email}</p>
          </div>
        ))}
      </div>

      {subjects.loading ? <Spinner label="Loading shared subjects" /> : null}
      {subjects.error ? <ErrorNote message={subjects.error} onRetry={subjects.reload} /> : null}

      {!subjects.loading && list.length === 0 ? (
        <EmptyState
          title="No shared subjects"
          body="Add a subject to this team to upload shared notes and generate distribution suggestions."
          action={
            <Link to={`/subjects/new?team=${team.id}`} className="btn-primary">
              Add shared subject
            </Link>
          }
        />
      ) : null}

      {list.length > 0 ? (
        <div className="card">
          <label className="label" htmlFor="team_subject">
            Shared subject
          </label>
          <select
            id="team_subject"
            className="field"
            value={activeId ?? ''}
            onChange={(e) => setSelected(Number(e.target.value))}
          >
            {list.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.name} — {subject.topic_count} topics
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {activeId ? <TeamIntelligence subjectId={activeId} /> : null}
    </section>
  )
}

async function loadTeamSubjects(teamId: number): Promise<Subject[] | null> {
  try {
    const all = await subjectApi.list()
    return all.filter((subject) => subject.team_id === teamId)
  } catch (error) {
    if (error instanceof Error) return []
    throw error
  }
}

function TeamIntelligence({ subjectId }: { subjectId: number }) {
  const [tab, setTab] = useState<'split' | 'matrix' | 'peers'>('split')
  const split = useAsync<TeamSplit | null>(() => loadSplit(subjectId), [subjectId, tab])
  const matrix = useAsync<KnowledgeMatrix | null>(
    () => (tab === 'matrix' ? teamApi.matrix(subjectId) : Promise.resolve(null)),
    [subjectId, tab],
  )
  const peers = useAsync<PeerRecommendations | null>(
    () => (tab === 'peers' ? teamApi.peers(subjectId) : Promise.resolve(null)),
    [subjectId, tab],
  )
  const { busy, error, run } = useAction()

  const tabs = [
    { key: 'split' as const, label: 'Distribution' },
    { key: 'matrix' as const, label: 'Knowledge matrix' },
    { key: 'peers' as const, label: 'Peer teaching' },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {tabs.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              tab === item.key
                ? 'bg-[var(--primary)] text-[var(--bg-main)]'
                : 'border border-slate-400 text-slate-700 hover:border-slate-500'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {error ? <ErrorNote message={error} /> : null}

      {tab === 'split' ? (
        <SplitTab subjectId={subjectId} data={split.data} loading={split.loading} onAccept={async (strategy, assignments) => {
          const result = await run(() => teamApi.applySplit(subjectId, { strategy, assignments }))
          if (result) split.reload()
        }} busy={busy} />
      ) : null}

      {tab === 'matrix' ? (
        matrix.loading ? (
          <Spinner label="Building the knowledge matrix" />
        ) : matrix.error ? (
          <ErrorNote message={matrix.error} onRetry={matrix.reload} />
        ) : matrix.data ? (
          <MatrixTab data={matrix.data} />
        ) : null
      ) : null}

      {tab === 'peers' ? (
        peers.loading ? (
          <Spinner label="Finding experts and learners" />
        ) : peers.error ? (
          <ErrorNote message={peers.error} onRetry={peers.reload} />
        ) : peers.data ? (
          <PeersTab data={peers.data} />
        ) : null
      ) : null}
    </div>
  )
}

function SplitTab({
  subjectId,
  data,
  loading,
  onAccept,
  busy,
}: {
  subjectId: number
  data: TeamSplit | null
  loading: boolean
  onAccept: (strategy: TeamSplit['suggestions'][number]['strategy'], assignments: unknown[]) => Promise<void>
  busy: boolean
}) {
  if (loading) return <Spinner label="Generating distribution suggestions" />
  if (!data || data.suggestions.length === 0) {
    return (
      <EmptyState
        title="No packages to distribute"
        body="Generate work packages for this subject first, then come back for distribution suggestions."
        action={
          <Link to={`/subjects/${subjectId}/analysis`} className="btn-primary">
            Go to analysis
          </Link>
        }
      />
    )
  }

  return (
    <div className="space-y-3">
      {data.suggestions.map((suggestion) => (
        <details key={suggestion.strategy} className="card group py-0" open={suggestion.strategy === 'time'}>
          <summary className="flex cursor-pointer flex-wrap items-center gap-3 py-3">
            <Pill className="bg-indigo-100 text-indigo-700">{suggestion.label}</Pill>
            <span className="min-w-0 flex-1 truncate text-sm text-slate-700">
              {suggestion.rationale}
            </span>
            <span className="text-xs tabular-nums text-slate-600">
              {formatMinutes(suggestion.total_minutes)}
            </span>
            <span className="text-xs text-slate-500 group-open:hidden">
              {suggestion.assignments.length} member(s)
            </span>
          </summary>
          <div className="space-y-2 border-t border-slate-300 py-3">
            {suggestion.assignments.map((assignment) => (
              <div key={assignment.user_id} className="rounded-lg border border-slate-300 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-slate-900">{assignment.user_name}</p>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <Pill className={difficultyPill(assignment.difficulty_load.hard)}>
                      {assignment.difficulty_load.hard} hard
                    </Pill>
                    <Pill className={difficultyPill(assignment.difficulty_load.medium)}>
                      {assignment.difficulty_load.medium} medium
                    </Pill>
                    <Pill className={difficultyPill(assignment.difficulty_load.easy)}>
                      {assignment.difficulty_load.easy} easy
                    </Pill>
                    <span className="tabular-nums text-slate-600">
                      {formatMinutes(assignment.minutes)}
                    </span>
                  </div>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {assignment.package_ids.length} package(s) · {assignment.topic_ids.length} topic(s)
                  {assignment.balance_score > 0
                    ? ` · balance ${(assignment.balance_score * 100).toFixed(0)}%`
                    : ''}
                </p>
                {assignment.note ? (
                  <p className="mt-1 text-xs text-slate-600">{assignment.note}</p>
                ) : null}
                {assignment.teaching_topics.length > 0 ? (
                  <p className="mt-1 text-xs text-emerald-300">
                    Suggested presenter for: {assignment.teaching_topics.join(', ')}
                  </p>
                ) : null}
              </div>
            ))}
            <button
              type="button"
              className="btn-primary"
              disabled={busy}
              onClick={() => void onAccept(suggestion.strategy, suggestion.assignments)}
            >
              Accept this split
            </button>
            <p className="text-xs text-slate-500">
              Suggestions only. Nothing is assigned until a team lead accepts.
            </p>
          </div>
        </details>
      ))}
    </div>
  )
}

function MatrixTab({ data }: { data: KnowledgeMatrix }) {
  const maxMastery = 1
  return (
    <div className="space-y-3">
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Topics" value={data.topics.length} />
        <Stat
          label="Uncovered"
          value={data.uncovered_topics.length}
          tone={data.uncovered_topics.length > 0 ? 'warn' : 'good'}
          hint="Nobody has started these"
        />
        <Stat label="Members" value={data.members.length} />
      </div>

      {data.concentration_warning ? (
        <div className="card border-amber-800/50 bg-amber-950/20 text-sm text-amber-200">
          {data.concentration_warning}
        </div>
      ) : null}

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-300">
              <th className="sticky left-0 bg-slate-100 px-3 py-2 text-left text-xs tracking-wide text-slate-500 uppercase">
                Member
              </th>
              {data.topics.map((topic) => (
                <th
                  key={topic.topic_id}
                  className="px-2 py-2 text-center text-xs font-normal text-slate-500"
                  title={topic.title}
                >
                  <span className="line-clamp-2 max-w-24">{topic.title}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.members.map((member) => (
              <tr key={member.user_id} className="border-b border-slate-300/60 last:border-0">
                <td className="sticky left-0 bg-slate-100 px-3 py-2">
                  <p className="font-medium whitespace-nowrap text-slate-900">{member.user_name}</p>
                  <p className="text-xs whitespace-nowrap text-slate-500">
                    {member.owned_topics} owned · {Math.round(member.coverage_percent * 100)}% avg
                  </p>
                </td>
                {member.cells.map((cell) => (
                  <td key={cell.topic_id} className="px-2 py-2 text-center">
                    <span
                      title={`${cell.knowledge_state} · mastery ${Math.round(cell.mastery * 100)}%${
                        cell.is_owner ? ' · owner' : ''
                      }`}
                      className={`mx-auto block size-6 rounded ${
                        cell.is_owner ? 'ring-2 ring-indigo-400 ring-offset-1 ring-offset-slate-900' : ''
                      }`}
                      style={{
                        backgroundColor: `oklch(0.7 0.16 ${clampPercent(cell.mastery * 100 * 1.4)})`,
                        opacity: 0.25 + 0.75 * clampPercent((cell.mastery / maxMastery) * 100),
                      }}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-500">
        Cell shade is mastery; a ring marks topic ownership. Hover a cell for detail.
      </p>
    </div>
  )
}

function PeersTab({ data }: { data: PeerRecommendations }) {
  return (
    <div className="space-y-3">
      <div className="card border-slate-300 bg-slate-100/40 text-xs text-slate-600">
        {data.note}
      </div>

      {data.recommendations.length === 0 ? (
        <EmptyState
          title="No peer teaching to suggest yet"
          body="Once members record progress on topics, the platform highlights who can teach what and who would benefit."
        />
      ) : (
        <div className="space-y-2">
          {data.recommendations.map((rec) => (
            <div key={rec.topic_id} className="card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-slate-900">{rec.topic_title}</p>
                <Pill className="bg-emerald-500/15 text-emerald-300">
                  {(rec.confidence * 100).toFixed(0)}% confidence
                </Pill>
              </div>
              <p className="mt-1 text-sm text-slate-700">{rec.reason}</p>
              <p className="mt-1 text-xs text-slate-500">
                Suggested: {rec.expert_name} → {rec.learner_names.join(', ')}
              </p>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h3 className="h2">Experts</h3>
          {data.experts.length === 0 ? (
            <p className="muted mt-2">No strong mastery recorded yet.</p>
          ) : (
            <ul className="mt-2 space-y-2">
              {data.experts.map((expert) => (
                <li key={expert.user_id} className="rounded-lg border border-slate-300 p-3">
                  <p className="text-sm font-medium text-slate-900">{expert.name}</p>
                  <p className="text-xs text-slate-500">
                    {expert.expert_topic_ids.length} expert topic(s) ·{' '}
                    {expert.near_expert_topic_ids.length} near ·{' '}
                    {Math.round(expert.overall_mastery * 100)}% average
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card">
          <h3 className="h2">Learners</h3>
          {data.learners.length === 0 ? (
            <p className="muted mt-2">Everyone has some ground covered.</p>
          ) : (
            <ul className="mt-2 space-y-2">
              {data.learners.map((learner) => (
                <li key={learner.user_id} className="rounded-lg border border-slate-300 p-3">
                  <p className="text-sm font-medium text-slate-900">{learner.name}</p>
                  <p className="text-xs text-slate-500">
                    Needs help on {learner.help_needed} topic(s) ·{' '}
                    {Math.round(learner.average_mastery * 100)}% average
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

function difficultyPill(count: number): string {
  if (count >= 3) return 'bg-rose-500/15 text-rose-300'
  if (count >= 1) return 'bg-amber-500/15 text-amber-300'
  return 'bg-slate-200 text-slate-600'
}

async function loadSplit(subjectId: number): Promise<TeamSplit | null> {
  try {
    return await teamApi.split(subjectId)
  } catch (error) {
    if (error instanceof Error && /work packages|solo/i.test(error.message)) return null
    throw error
  }
}
