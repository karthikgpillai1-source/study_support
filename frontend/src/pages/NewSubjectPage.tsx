import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { subjectApi, teamApi } from '@/api/endpoints'
import type { Team } from '@/api/types'
import { ErrorNote, SectionHeader } from '@/components/ui'
import { useAsync, useAction } from '@/lib/useAsync'
import { addDaysIso, modeLabel, todayIso } from '@/lib/format'

const KNOWLEDGE_LEVELS = [
  { value: 'novice', label: '1 · Novice', hint: 'New to this subject — build from scratch' },
  { value: 'beginner', label: '2 · Beginner', hint: 'Recall the basics, needs guided coverage' },
  {
    value: 'intermediate',
    label: '3 · Intermediate',
    hint: 'Comfortable fundamentals, needs depth',
  },
  { value: 'advanced', label: '4 · Advanced', hint: 'Strong grasp, focus on nuance' },
  { value: 'expert', label: '5 · Expert', hint: 'Near mastery — verify and revise' },
]

const MODES = [
  {
    value: 'fast_exam',
    label: 'Fast exam preparation',
    hint: 'High-yield topics first, revision compressed, nothing scheduled past the exam.',
  },
  {
    value: 'college_pace',
    label: 'Follow college pace',
    hint: 'Even coverage against the teaching schedule, longer revision cycles.',
  },
]

const COLORS = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#a855f7', '#ec4899']
const WEEKDAYS = [
  { value: 1, label: 'Mon' },
  { value: 2, label: 'Tue' },
  { value: 3, label: 'Wed' },
  { value: 4, label: 'Thu' },
  { value: 5, label: 'Fri' },
  { value: 6, label: 'Sat' },
  { value: 7, label: 'Sun' },
]

export function NewSubjectPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { busy, error, run } = useAction()
  const { data: teamList } = useAsync(() => teamApi.list(), [])

  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [knowledgeLevel, setKnowledgeLevel] = useState('beginner')
  const [mode, setMode] = useState('fast_exam')
  const [examDate, setExamDate] = useState(addDaysIso(todayIso(), 21))
  const [color, setColor] = useState(COLORS[0])
  const [dailyMinutes, setDailyMinutes] = useState(120)
  const [startTime, setStartTime] = useState('18:00')
  const [restDays, setRestDays] = useState<number[]>([])
  const [teamId, setTeamId] = useState<number | null>(
    params.get('team') ? Number(params.get('team')) : null,
  )

  const teams: Team[] = teamList ?? []

  function toggleRestDay(day: number) {
    setRestDays((current) =>
      current.includes(day) ? current.filter((d) => d !== day) : [...current, day].sort(),
    )
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const created = await run(() =>
      subjectApi.create({
        name,
        code,
        description,
        knowledge_level: knowledgeLevel,
        study_mode: mode,
        exam_date: examDate || null,
        color,
        daily_minutes: dailyMinutes,
        start_time: startTime,
        rest_days: restDays,
        team_id: teamId,
      }),
    )
    if (created) navigate(`/subjects/${created.id}/upload`)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <SectionHeader
        title="New subject"
        description="These settings drive difficulty scoring, time estimates and the whole plan."
      />

      <form className="card space-y-6" onSubmit={onSubmit}>
        <div className="grid gap-4 sm:grid-cols-[2fr_1fr]">
          <div>
            <label className="label" htmlFor="name">
              Subject name
            </label>
            <input
              id="name"
              className="field"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Operating Systems"
              required
              minLength={2}
            />
          </div>
          <div>
            <label className="label" htmlFor="code">
              Code (optional)
            </label>
            <input
              id="code"
              className="field"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="CS301"
            />
          </div>
        </div>

        <div>
          <label className="label" htmlFor="description">
            Description (optional)
          </label>
          <textarea
            id="description"
            className="field min-h-20"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What this course covers and what the exam is like."
          />
        </div>

        <fieldset>
          <legend className="label">Knowledge level</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {KNOWLEDGE_LEVELS.map((level) => (
              <label
                key={level.value}
                className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition ${
                  knowledgeLevel === level.value
                    ? 'border-indigo-500 bg-indigo-500/10'
                    : 'border-slate-300 hover:border-slate-400'
                }`}
              >
                <input
                  type="radio"
                  name="knowledge"
                  value={level.value}
                  checked={knowledgeLevel === level.value}
                  onChange={() => setKnowledgeLevel(level.value)}
                  className="mt-1 accent-indigo-500"
                />
                <span>
                  <span className="block text-sm font-semibold text-slate-900">{level.label}</span>
                  <span className="block text-xs text-slate-600">{level.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="label">Study mode</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {MODES.map((option) => (
              <label
                key={option.value}
                className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition ${
                  mode === option.value
                    ? 'border-indigo-500 bg-indigo-500/10'
                    : 'border-slate-300 hover:border-slate-400'
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  value={option.value}
                  checked={mode === option.value}
                  onChange={() => setMode(option.value)}
                  className="mt-1 accent-indigo-500"
                />
                <span>
                  <span className="block text-sm font-semibold text-slate-900">
                    {option.label}
                  </span>
                  <span className="block text-xs text-slate-600">{option.hint}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-slate-500">
            Currently: {modeLabel(mode)}. You can switch later without losing the subject.
          </p>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="exam_date">
              Exam date
            </label>
            <input
              id="exam_date"
              type="date"
              className="field"
              value={examDate}
              min={todayIso()}
              onChange={(e) => setExamDate(e.target.value)}
            />
            <p className="mt-1 text-xs text-slate-500">Leave blank for no deadline.</p>
          </div>
          <div>
            <label className="label" htmlFor="team">
              Study team
            </label>
            <select
              id="team"
              className="field"
              value={teamId ?? ''}
              onChange={(e) => setTeamId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Solo (just me)</option>
              {teams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name} ({team.members.length} members)
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-slate-500">
              {teams.length === 0 ? 'No teams yet — create one from the Team page.' : null}
            </p>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="daily_minutes">
              Study time per day
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
          </div>
          <div>
            <label className="label" htmlFor="start_time">
              Usual start time
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
        </div>

        <fieldset>
          <legend className="label">Rest days</legend>
          <div className="flex flex-wrap gap-2">
            {WEEKDAYS.map((day) => (
              <button
                key={day.value}
                type="button"
                onClick={() => toggleRestDay(day.value)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  restDays.includes(day.value)
                    ? 'bg-[var(--primary)] text-[var(--bg-main)]'
                    : 'border border-slate-400 text-slate-700 hover:border-slate-500'
                }`}
              >
                {day.label}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="label">Colour</legend>
          <div className="flex flex-wrap gap-2">
            {COLORS.map((option) => (
              <button
                key={option}
                type="button"
                aria-label={`Colour ${option}`}
                onClick={() => setColor(option)}
                className={`size-8 rounded-lg transition ${
                  color === option ? 'ring-2 ring-white ring-offset-2 ring-offset-slate-900' : ''
                }`}
                style={{ backgroundColor: option }}
              />
            ))}
          </div>
        </fieldset>

        {error ? <ErrorNote message={error} /> : null}

        <div className="flex items-center gap-3 border-t border-slate-300 pt-4">
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Creating…' : 'Create and upload notes'}
          </button>
          <button type="button" className="btn-ghost" onClick={() => navigate('/dashboard')}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
