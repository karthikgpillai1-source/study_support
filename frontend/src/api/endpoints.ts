/** Every backend call in one place, so pages stay declarative. */

import { api } from './client'
import type {
  AdaptiveReport,
  Analysis,
  Dashboard,
  DocumentRecord,
  Intelligence,
  KnowledgeMatrix,
  OwnershipRow,
  PackagesResponse,
  PeerRecommendations,
  Plan,
  SplitStrategy,
  Subject,
  SubjectProgress,
  Team,
  TeamSplit,
  TokenResponse,
  User,
  WeekSummary,
} from './types'

export interface SubjectInput {
  name: string
  code?: string
  description?: string
  knowledge_level: string
  study_mode: string
  exam_date?: string | null
  color?: string
  daily_minutes?: number
  start_time?: string
  rest_days?: number[]
  team_id?: number | null
}

export const authApi = {
  register: (body: {
    email: string
    full_name: string
    password: string
    daily_minutes?: number
    preferred_start_time?: string
  }) => api.post<TokenResponse>('/auth/register', body),
  login: (body: { email: string; password: string }) =>
    api.post<TokenResponse>('/auth/login', body),
  me: () => api.get<User>('/auth/me'),
  updateProfile: (body: { full_name?: string; daily_minutes?: number; preferred_start_time?: string }) =>
    api.patch<User>('/auth/me', body),
}

export const subjectApi = {
  list: () => api.get<Subject[]>('/subjects'),
  get: (id: number) => api.get<Subject>(`/subjects/${id}`),
  create: (body: SubjectInput) => api.post<Subject>('/subjects', body),
  update: (id: number, body: Partial<SubjectInput>) =>
    api.patch<Subject>(`/subjects/${id}`, body),
  remove: (id: number) => api.delete<void>(`/subjects/${id}`),
}

export const uploadApi = {
  documents: (subjectId: number) => api.get<DocumentRecord[]>(`/subjects/${subjectId}/documents`),
  upload: (subjectId: number, file: File, analyzeNow: boolean) => {
    const form = new FormData()
    form.append('file', file)
    form.append('analyze_now', String(analyzeNow))
    form.append('use_llm', 'true')
    return api.upload<{ document: DocumentRecord; text_preview: string; characters: number }>(
      `/subjects/${subjectId}/documents`,
      form,
    )
  },
  remove: (documentId: number) => api.delete<void>(`/documents/${documentId}`),
}

export const intelligenceApi = {
  get: (subjectId: number) => api.get<Intelligence>(`/subjects/${subjectId}/intelligence`),
  analyze: (subjectId: number, useLlm = true) =>
    api.post<Intelligence>(`/subjects/${subjectId}/analyze`, undefined, { use_llm: useLlm }),
  analysis: (subjectId: number) => api.get<Analysis>(`/subjects/${subjectId}/analysis`),
  packages: (subjectId: number) => api.get<PackagesResponse>(`/subjects/${subjectId}/packages`),
  generatePackages: (subjectId: number, includeRevision = true) =>
    api.post<PackagesResponse>(`/subjects/${subjectId}/packages`, undefined, {
      include_revision: includeRevision,
    }),
}

export const plannerApi = {
  generate: (
    subjectId: number,
    body: { horizon_days?: number; daily_minutes?: number; include_revision?: boolean; mode?: string },
  ) => api.post<Plan>(`/subjects/${subjectId}/plan`, body),
  get: (subjectId: number, days = 14) => api.get<Plan>(`/subjects/${subjectId}/plan`, { days }),
  week: (subjectId: number) => api.get<WeekSummary>(`/subjects/${subjectId}/plan/week`),
  adaptive: (subjectId: number) => api.get<AdaptiveReport>(`/subjects/${subjectId}/plan/adaptive`),
  replan: (subjectId: number) => api.get<Plan>(`/subjects/${subjectId}/plan/replan`),
  setMode: (subjectId: number, mode: string) =>
    api.post<Plan>(`/subjects/${subjectId}/plan/mode`, undefined, { mode }),
  setAvailability: (
    subjectId: number,
    body: { daily_minutes: number; start_time: string; rest_days: number[] },
  ) => api.patch<unknown>(`/subjects/${subjectId}/availability`, body),
  updateBlock: (
    blockId: number,
    body: { status?: string; actual_minutes?: number; note?: string },
  ) => api.patch<import('./types').StudyBlock>(`/blocks/${blockId}`, body),
}

export const progressApi = {
  dashboard: () => api.get<Dashboard>('/dashboard'),
  subject: (subjectId: number) => api.get<SubjectProgress>(`/subjects/${subjectId}/progress`),
  record: (body: {
    topic_id: number
    event: 'started' | 'completed' | 'partial' | 'skipped'
    minutes_spent?: number
    confidence?: number
    note?: string
    block_id?: number | null
  }) => api.post<SubjectProgress>('/progress', body),
}

export const teamApi = {
  list: () => api.get<Team[]>('/teams'),
  create: (name: string, description = '') => api.post<Team>('/teams', { name, description }),
  join: (joinCode: string) => api.post<Team>('/teams/join', { join_code: joinCode }),
  get: (teamId: number) => api.get<Team>(`/teams/${teamId}`),
  leave: (teamId: number) => api.delete<void>(`/teams/${teamId}/leave`),
  remove: (teamId: number) => api.delete<void>(`/teams/${teamId}`),
  split: (subjectId: number, strategy?: SplitStrategy) =>
    api.get<TeamSplit>(`/subjects/${subjectId}/split`, strategy ? { strategy } : undefined),
  applySplit: (
    subjectId: number,
    body: { strategy: SplitStrategy; assignments: unknown[] },
  ) => api.post<{ assignments_applied: number }>(`/subjects/${subjectId}/split/apply`, body),
  ownership: (subjectId: number) => api.get<OwnershipRow[]>(`/subjects/${subjectId}/ownership`),
  setOwnership: (
    subjectId: number,
    body: { topic_ids: number[]; user_id: number; role?: string },
  ) => api.post<unknown>(`/subjects/${subjectId}/ownership`, body),
  matrix: (subjectId: number) => api.get<KnowledgeMatrix>(`/subjects/${subjectId}/matrix`),
  peers: (subjectId: number) => api.get<PeerRecommendations>(`/subjects/${subjectId}/peers`),
  signal: (subjectId: number, topicId: number, kind: 'taught' | 'mastered' | 'struggling') =>
    api.post<unknown>(`/subjects/${subjectId}/peers/signal`, undefined, {
      topic_id: topicId,
      kind,
    }),
}

export const healthApi = {
  check: () =>
    api.get<{
      status: string
      llm_provider: string
      supported_uploads: string[]
      planner_rules: { max_daily_minutes: number; llm_used: boolean }
    }>('/health'),
}
