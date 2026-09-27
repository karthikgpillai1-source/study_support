import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { subjectApi, uploadApi } from '@/api/endpoints'
import type { DocumentRecord, Subject } from '@/api/types'
import { EmptyState, ErrorNote, SectionHeader, Spinner } from '@/components/ui'
import { formatBytes, formatDate } from '@/lib/format'
import { useAction, useAsync } from '@/lib/useAsync'

const ACCEPT = '.pdf,.docx,.txt,.md,.text'
const MAX_MB = 25

export function UploadPage() {
  const { subjectId } = useParams()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)

  const subjects = useAsync(() => subjectApi.list(), [])
  const documents = useAsync(
    () => (subjectId ? uploadApi.documents(Number(subjectId)) : Promise.resolve(null)),
    [subjectId],
  )
  const { busy, error, run } = useAction()

  const [dragging, setDragging] = useState(false)
  const [analyzeNow, setAnalyzeNow] = useState(true)
  const [lastPreview, setLastPreview] = useState<{ name: string; preview: string } | null>(null)
  const [subjectsFilter, setSubjectsFilter] = useState('')

  const all: Subject[] = subjects.data ?? []
  const visible = all.filter((s) => s.name.toLowerCase().includes(subjectsFilter.toLowerCase()))

  async function upload(files: FileList | null) {
    const file = files?.[0]
    if (!file) return
    if (!subjectId) {
      await run(() => Promise.reject(new Error('Choose a subject first.')))
      return
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      await run(() => Promise.reject(new Error(`${file.name} is larger than ${MAX_MB} MB.`)))
      return
    }
    const result = await run(() => uploadApi.upload(Number(subjectId), file, analyzeNow))
    if (result) {
      setLastPreview({ name: result.document.filename, preview: result.text_preview })
      documents.reload()
      subjects.reload()
    }
  }

  if (subjects.loading) return <Spinner label="Loading your subjects" />

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Upload centre"
        description="PDF, DOCX or TXT. Each upload can trigger analysis immediately."
      />

      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="space-y-4">
          <div className="card space-y-3">
            <div>
              <label className="label" htmlFor="subject">
                Target subject
              </label>
              {subjectId ? (
                <div className="flex items-center gap-3">
                  <input className="field" value={all.find((s) => s.id === Number(subjectId))?.name ?? ''} readOnly />
                  <Link to="/upload" className="btn-secondary text-xs whitespace-nowrap">
                    Change
                  </Link>
                </div>
              ) : (
                <>
                  <input
                    id="subject"
                    className="field"
                    placeholder="Filter subjects…"
                    value={subjectsFilter}
                    onChange={(e) => setSubjectsFilter(e.target.value)}
                  />
                  <div className="max-h-48 space-y-1 overflow-y-auto">
                    {visible.length === 0 ? (
                      <p className="py-2 text-sm text-slate-500">
                        No subjects yet.{' '}
                        <Link className="link" to="/subjects/new">
                          Create one
                        </Link>
                        .
                      </p>
                    ) : (
                      visible.map((subject) => (
                        <button
                          key={subject.id}
                          type="button"
                          onClick={() => navigate(`/subjects/${subject.id}/upload`)}
                          className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition hover:bg-slate-200"
                        >
                          <span className="flex items-center gap-2">
                            <span
                              className="size-2.5 rounded-full"
                              style={{ backgroundColor: subject.color }}
                            />
                            {subject.name}
                          </span>
                          <span className="text-xs text-slate-500">
                            {subject.document_count} file(s) · {subject.topic_count} topics
                          </span>
                        </button>
                      ))
                    )}
                  </div>
                </>
              )}
            </div>

            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={analyzeNow}
                onChange={(e) => setAnalyzeNow(e.target.checked)}
                className="accent-indigo-500"
              />
              Run analysis immediately after upload
            </label>
          </div>

          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              void upload(e.dataTransfer.files)
            }}
            className={`card grid place-items-center gap-3 border-dashed py-12 text-center transition ${
              dragging ? 'border-indigo-400 bg-indigo-500/10' : 'border-slate-400'
            }`}
          >
            <p className="text-base font-semibold text-slate-900">
              {dragging ? 'Drop to upload' : 'Drag and drop your notes here'}
            </p>
            <p className="text-sm text-slate-600">
              PDF, DOCX or TXT up to {MAX_MB} MB. Scanned PDFs need OCR and are not supported yet.
            </p>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => inputRef.current?.click()}
              disabled={!subjectId || busy}
            >
              {busy ? 'Uploading and analysing…' : 'Choose a file'}
            </button>
            {!subjectId ? (
              <p className="text-xs text-amber-400">Pick a subject above first.</p>
            ) : null}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => {
                void upload(e.target.files)
                e.target.value = ''
              }}
            />
          </div>

          {error ? <ErrorNote message={error} /> : null}
        </div>

        <div className="space-y-4">
          <div>
            <h2 className="h2">Uploaded files</h2>
            {subjectId ? (
              <DocumentsList
                documents={documents}
                onChanged={() => {
                  documents.reload()
                  subjects.reload()
                }}
              />
            ) : (
              <p className="muted mt-1">Choose a subject to see its files.</p>
            )}
          </div>

          {lastPreview ? (
            <div className="card">
              <h3 className="text-sm font-semibold text-slate-900">
                Extracted text preview — {lastPreview.name}
              </h3>
              <p className="mt-2 max-h-64 overflow-y-auto font-mono text-xs leading-relaxed whitespace-pre-wrap text-slate-600">
                {lastPreview.preview}
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function DocumentsList({
  documents,
  onChanged,
}: {
  documents: ReturnType<typeof useAsync<DocumentRecord[] | null>>
  onChanged: () => void
}) {
  const { busy, error, run } = useAction()
  if (documents.loading) return <Spinner label="Loading files" />
  if (documents.error) return <ErrorNote message={documents.error} onRetry={documents.reload} />
  const rows = documents.data ?? []
  if (rows.length === 0) {
    return <EmptyState title="No files yet" body="Upload lecture notes, a textbook extract or a handout." />
  }
  return (
    <div className="mt-2 space-y-2">
      {error ? <ErrorNote message={error} /> : null}
      {rows.map((doc) => (
        <div
          key={doc.id}
          className="card flex flex-wrap items-center justify-between gap-3 py-3"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-900">{doc.filename}</p>
            <p className="text-xs text-slate-500">
              {formatBytes(doc.size_bytes)} · {doc.word_count.toLocaleString()} words ·{' '}
              {doc.page_count} page(s) · via {doc.extractor} · {formatDate(doc.created_at)}
            </p>
            {doc.warnings.length > 0 ? (
              <p className="mt-1 text-xs text-amber-400">{doc.warnings[0]}</p>
            ) : null}
          </div>
          <button
            type="button"
            className="btn-danger py-1 text-xs"
            disabled={busy}
            onClick={async () => {
              const result = await run(() => uploadApi.remove(doc.id))
              if (result !== null) onChanged()
            }}
          >
            Delete
          </button>
        </div>
      ))}
    </div>
  )
}
