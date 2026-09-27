import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { healthApi } from '@/api/endpoints'
import { useAsync } from '@/lib/useAsync'
import { useAuth } from '@/context/auth-context'

const STEPS = [
  {
    n: '01',
    title: 'Upload your notes',
    body: 'Drop in a PDF, DOCX or TXT file. The extraction layer pulls out clean text and preserves page and heading structure.',
  },
  {
    n: '02',
    title: 'Get study intelligence',
    body: 'Topics, subtopics, concepts, keywords, learning objectives, definitions, procedures, formulas and important facts — each scored for difficulty and time.',
  },
  {
    n: '03',
    title: 'Get work packages',
    body: 'Material is grouped into packages of at most 90 minutes, each broken into 10–30 minute blocks you can actually finish.',
  },
  {
    n: '04',
    title: 'Get a study plan',
    body: 'A deterministic planner fits the work into your real availability, up to your exam date, with spaced revision built in.',
  },
  {
    n: '05',
    title: 'Track and adapt',
    body: 'Log what you complete. The planner detects falling behind or racing ahead and recalculates the rest of the schedule.',
  },
]

const GUARANTEES = [
  {
    title: 'Your plan is not AI-written',
    body: 'Scheduling, priority scoring, time estimates and workload splits are pure deterministic Python. Re-running with the model disabled produces an identical plan.',
  },
  {
    title: 'Works with no API key',
    body: 'The structural analyser runs entirely offline. Add a Gemini key for richer content structuring; nothing else changes.',
  },
  {
    title: 'Recommendations, never assignments',
    body: 'Peer teaching and topic ownership are always suggested. A team lead has to accept them before anything is assigned.',
  },
]

export function LandingPage() {
  const { user } = useAuth()
  const { data: health } = useAsync(() => healthApi.check(), [])
  const [provider, setProvider] = useState<string>('checking…')
  useEffect(() => {
    if (health) setProvider(health.llm_provider)
  }, [health])

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5">
        <div className="flex items-center gap-2">
          <img src="/logo.jpg" alt="Study Intelligence" className="size-8 rounded-md object-contain" />
          <span className="text-sm font-semibold">Study Intelligence</span>
        </div>
        <nav className="flex items-center gap-2">
          {user ? (
            <Link to="/dashboard" className="btn-primary text-sm">
              Go to dashboard
            </Link>
          ) : (
            <>
              <Link to="/login" className="btn-ghost text-sm">
                Sign in
              </Link>
              <Link to="/register" className="btn-primary text-sm">
                Get started
              </Link>
            </>
          )}
        </nav>
      </header>

      <section className="mx-auto max-w-6xl px-4 pt-10 pb-16">
        <p className="badge bg-[var(--bg-elevated)] text-[var(--primary)] ring-1 ring-[var(--accent-success)]">
          Study planning &amp; workload management
        </p>
        <h1 className="mt-4 max-w-3xl text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
          Turn unstructured notes into a study plan you will actually follow.
        </h1>
        <p className="mt-4 max-w-2xl text-lg text-slate-600">
          Upload your material. Get structured study intelligence, realistic time estimates,
          90-minute work packages and a daily plan built around your actual availability and
          exam date. Solo or as a study team.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          {user ? (
            <Link to="/dashboard" className="btn-primary">
              Go to your dashboard
            </Link>
          ) : (
            <>
              <Link to="/register" className="btn-primary">
                Create an account
              </Link>
              <Link to="/login" className="btn-secondary">
                I already have one
              </Link>
            </>
          )}
        </div>
        <p className="mt-4 text-xs text-slate-500">
          Content structuring provider: <span className="text-slate-600">{provider}</span> — the
          planner never uses one.
        </p>
      </section>

      <section className="border-t border-slate-300/70 bg-slate-50/40">
        <div className="mx-auto max-w-6xl px-4 py-16">
          <h2 className="text-2xl font-semibold text-slate-900">The flow</h2>
          <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {STEPS.map((step) => (
              <li key={step.n} className="card">
                <span className="text-xs font-bold tracking-widest text-[var(--accent-warning)]">{step.n}</span>
                <h3 className="mt-2 text-sm font-semibold text-slate-900">{step.title}</h3>
                <p className="mt-1.5 text-sm text-slate-600">{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16">
        <h2 className="text-2xl font-semibold text-slate-900">Study modes</h2>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <div className="card">
            <h3 className="h2">Fast exam preparation</h3>
            <p className="mt-2 text-sm text-slate-600">
              Deadline pressure dominates. High-importance topics first, revision compressed
              into +1 and +3 day passes, and nothing is scheduled past the exam date.
            </p>
          </div>
          <div className="card">
            <h3 className="h2">Follow college pace</h3>
            <p className="mt-2 text-sm text-slate-600">
              Even coverage against the teaching schedule, steady weekly goals and longer
              revision cycles at +3, +10 and +21 days.
            </p>
          </div>
        </div>
      </section>

      <section className="border-t border-slate-300/70 bg-slate-50/40">
        <div className="mx-auto max-w-6xl px-4 py-16">
          <h2 className="text-2xl font-semibold text-slate-900">What the platform will not do</h2>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {GUARANTEES.map((item) => (
              <div key={item.title} className="card">
                <h3 className="text-sm font-semibold text-slate-900">{item.title}</h3>
                <p className="mt-1.5 text-sm text-slate-600">{item.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16 text-center">
        <h2 className="text-2xl font-semibold text-slate-900">Start with one subject</h2>
        <p className="mx-auto mt-2 max-w-xl text-slate-600">
          Set your knowledge level, exam date and study mode, then upload a single set of notes.
        </p>
        {user ? (
          <Link to="/dashboard" className="btn-primary mt-6">
            Continue to dashboard
          </Link>
        ) : (
          <Link to="/register" className="btn-primary mt-6">
            Create an account
          </Link>
        )}
      </section>
    </div>
  )
}
