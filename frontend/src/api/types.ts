/**
 * Types mirroring the FastAPI response models.
 *
 * Kept hand-written and narrow: only the fields the UI actually reads. The
 * backend's OpenAPI schema is the source of truth (see /docs).
 */

export type Difficulty = 'easy' | 'medium' | 'hard'
export type KnowledgeLevel = 'novice' | 'beginner' | 'intermediate' | 'advanced' | 'expert'
export type StudyMode = 'fast_exam' | 'college_pace'
export type KnowledgeState = 'unknown' | 'learning' | 'familiar' | 'strong' | 'mastered'
export type TopicStatus = 'pending' | 'in_progress' | 'completed' | 'skipped'
export type BlockStatus = 'planned' | 'done' | 'partial' | 'missed' | 'skipped'
export type UnitType = 'learn' | 'practice' | 'teach' | 'revision' | 'mock_test' | 'break'
export type PackageType = 'study' | 'revision'
export type SplitStrategy = 'topic' | 'difficulty' | 'time' | 'teaching' | 'revision'

export interface User {
  id: number
  email: string
  full_name: string
  daily_minutes: number
  preferred_start_time: string
  timezone: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface Subject {
  id: number
  name: string
  code: string
  description: string
  color: string
  knowledge_level: KnowledgeLevel
  study_mode: StudyMode
  exam_date: string | null
  team_id: number | null
  owner_id: number | null
  daily_minutes: number
  start_time: string
  rest_days: number[]
  created_at: string
  document_count: number
  topic_count: number
  total_minutes: number
  completed_minutes: number
  progress_percent: number
  days_to_exam: number | null
  has_intelligence: boolean
  has_active_plan: boolean
}

export interface DocumentRecord {
  id: number
  subject_id: number
  filename: string
  size_bytes: number
  page_count: number
  word_count: number
  status: string
  extractor: string
  warnings: string[]
  created_at: string
}

export interface Topic {
  id: number
  module_title: string
  title: string
  position: number
  difficulty: Difficulty
  estimated_minutes: number
  revision_minutes: number
  importance: number
  keywords: string[]
  learning_objectives: string[]
  definitions: string[]
  procedures: string[]
  formulas: string[]
  important_facts: string[]
  subtopics: string[]
  concepts: string[]
  status: TopicStatus
  knowledge_state: KnowledgeState
  mastery: number
}

export interface Intelligence {
  id: number
  subject_id: number
  source: string
  summary: string
  modules: { title: string; position: number; topic_titles: string[]; summary: string }[]
  keywords: string[]
  learning_objectives: string[]
  formulas: string[]
  total_minutes: number
  topic_count: number
  confidence: number
  created_at: string
  topics: Topic[]
}

export interface TimeEstimates {
  subject_id: number
  total_minutes: number
  revision_minutes: number
  grand_total_minutes: number
  per_module: { module: string; minutes: number; revision_minutes: number; topics: number }[]
  days_required: number
  feasible: boolean
  message: string
  breakdown: {
    easy: number
    medium: number
    hard: number
    minutes_easy: number
    minutes_medium: number
    minutes_hard: number
  }
}

export interface StudyUnit {
  id: number
  package_id: number
  topic_id: number | null
  type: UnitType
  title: string
  position: number
  minutes: number
  objectives: string[]
  resources: string[]
  done: boolean
}

export interface WorkPackage {
  id: number
  subject_id: number
  type: PackageType
  title: string
  position: number
  total_minutes: number
  difficulty: Difficulty
  topic_ids: number[]
  revision_of_package_id: number | null
  suggested_owner_id: number | null
  completed: boolean
  units: StudyUnit[]
}

export interface PackagesResponse {
  subject_id: number
  strategy: string
  max_minutes_per_package: number
  packages: WorkPackage[]
}

export interface Analysis {
  subject: Subject
  intelligence: Intelligence | null
  estimates: TimeEstimates | null
  packages: WorkPackage[]
  warnings: string[]
}

export interface StudyBlock {
  id: number
  plan_id: number
  unit_id: number | null
  package_id: number | null
  topic_id: number | null
  day: string
  start_time: string
  end_time: string
  minutes: number
  block_index: number
  kind: UnitType
  title: string
  priority: number
  status: BlockStatus
  is_break: boolean
  actual_minutes: number
  completed_at: string | null
  locked: boolean
  note: string
}

export interface DayPlan {
  day: string
  weekday: number
  is_rest_day: boolean
  budget_minutes: number
  planned_minutes: number
  completed_minutes: number
  completion_percent: number
  blocks: StudyBlock[]
}

export interface Plan {
  id: number
  subject_id: number
  generated_for: string
  week_start: string
  strategy: string
  study_mode: StudyMode
  daily_budget_minutes: number
  planned_minutes: number
  version: number
  is_active: boolean
  reason: string
  meta: {
    reason_code?: string
    revision_offsets_days?: number[]
    unscheduled_unit_ids?: number[]
    days_left_at_start?: number | null
    [key: string]: unknown
  }
  created_at: string
  days: DayPlan[]
}

export interface WeekSummary {
  week_start: string
  week_end: string
  planned_minutes: number
  completed_minutes: number
  blocks_done: number
  blocks_total: number
  by_day: {
    day: string
    planned_minutes: number
    completed_minutes: number
    completion_percent: number
    is_rest_day: boolean
  }[]
  by_kind: { kind: string; minutes: number }[]
}

export interface AdaptiveAction {
  kind: string
  label: string
  rationale: string
  daily_minutes: number | null
  horizon_days: number | null
  include_revision: boolean | null
  scope: string
}

export interface AdaptiveReport {
  status: 'on_track' | 'behind' | 'ahead' | 'availability_changed' | 'complete'
  summary: string
  actions: AdaptiveAction[]
  remaining_minutes: number
  required_daily_minutes: number
  days_left: number | null
  feasible: boolean
}

export interface TopicProgress {
  topic_id: number
  title: string
  status: TopicStatus
  knowledge_state: KnowledgeState
  mastery: number
  minutes_spent: number
  events: number
  last_touched: string | null
}

export interface SubjectProgress {
  subject_id: number
  subject_name: string
  total_minutes: number
  completed_minutes: number
  progress_percent: number
  topics_total: number
  topics_completed: number
  topics_in_progress: number
  revision_minutes_completed: number
  streak_days: number
  daily_series: { day: string; minutes: number }[]
  topic_progress: TopicProgress[]
}

export interface Dashboard {
  subjects: Subject[]
  today: {
    id: number
    subject_id: number
    subject_name: string
    color: string
    title: string
    start_time: string
    end_time: string
    minutes: number
    kind: UnitType
    status: BlockStatus
  }[]
  upcoming_deadlines: {
    subject_id: number
    name: string
    exam_date: string
    days_left: number
    progress_percent: number
    feasible: boolean
  }[]
  plans: {
    id: number
    subject_id: number
    subject_name: string
    color: string
    generated_for: string
    horizon_days: number
    planned_minutes: number
    daily_budget_minutes: number
    unscheduled: number
    reason: string
  }[]
  totals: {
    subjects: number
    topics: number
    minutes_planned: number
    minutes_completed: number
    blocks_today: number
    minutes_today: number
  }
  team: {
    id: number
    name: string
    join_code: string
    role: string
    members: number
    subjects: number
  } | null
}

export interface TeamMember {
  id: number
  user_id: number
  role: string
  joined_at: string
  full_name: string
  email: string
}

export interface Team {
  id: number
  name: string
  join_code: string
  description: string
  owner_id: number
  created_by_id: number
  members: TeamMember[]
  subjects: { id: number; name: string; exam_date: string | null; color: string }[]
  created_at: string
}

export interface SplitAssignment {
  user_id: number
  user_name: string
  package_ids: number[]
  topic_ids: number[]
  minutes: number
  difficulty_load: { easy: number; medium: number; hard: number }
  balance_score: number
  teaching_topics: string[]
  revision_topic_ids: number[]
  note: string
}

export interface SplitSuggestion {
  strategy: SplitStrategy
  label: string
  rationale: string
  total_minutes: number
  assignments: SplitAssignment[]
}

export interface TeamSplit {
  subject_id: number
  suggestions: SplitSuggestion[]
  generated_at: string
}

export interface MatrixCell {
  topic_id: number
  mastery: number
  knowledge_state: KnowledgeState
  status: TopicStatus
  is_owner: boolean
}

export interface KnowledgeMatrix {
  subject_id: number
  topic_ids: number[]
  topics: { topic_id: number; title: string; position: number }[]
  members: {
    user_id: number
    user_name: string
    cells: MatrixCell[]
    strong_count: number
    learning_count: number
    unknown_count: number
    owned_topics: number
    coverage_percent: number
  }[]
  uncovered_topics: number[]
  concentration_warning: string | null
}

export interface PeerRecommendations {
  subject_id: number
  experts: {
    user_id: number
    name: string
    expert_topic_ids: number[]
    near_expert_topic_ids: number[]
    teaching_load: number
    overall_mastery: number
    confidence: number
  }[]
  learners: {
    user_id: number
    name: string
    help_topic_ids: number[]
    help_needed: number
    average_mastery: number
  }[]
  recommendations: {
    topic_id: number
    topic_title: string
    expert_id: number
    expert_name: string
    learner_ids: number[]
    learner_names: string[]
    reason: string
    confidence: number
    action: string
  }[]
  note: string
}

export interface OwnershipRow {
  topic_id: number
  topic_title: string
  user_id: number
  user_name: string
  role: string
  strategy: string
  accepted: boolean
}
