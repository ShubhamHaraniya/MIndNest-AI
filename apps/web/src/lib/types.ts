export type Language = "en" | "hi" | "gu";

export type User = {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
  timezone: string;
  ui_language: Language;
  answer_language: Language | null;
  onboarding_step: number;
  onboarding_completed: boolean;
  mask_personal_data: boolean;
  is_admin: boolean;
  /** Self-declared; "My college" in the Materials Library is everyone who typed the same name. */
  institution_name: string;
};

export type Subject = {
  id: string;
  name: string;
  course_code: string | null;
  semester: string | null;
  description: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  material_count: number;
};

export type SubjectPage = {
  items: Subject[];
  next_cursor: string | null;
  total: number;
};

export type DeleteImpact = {
  materials: number;
  topics: number;
  conversations_kept: number;
};

export type MaterialKind = "material" | "past_paper" | "note" | "assignment";
export type MaterialStatus = "uploaded" | "processing" | "ready" | "failed";

export type Material = {
  id: string;
  subject_id: string;
  filename: string;
  kind: MaterialKind;
  mime_type: string | null;
  size_bytes: number | null;
  status: MaterialStatus;
  /** A short code such as "no_text"; translate it with the materials.error.* messages. */
  error: string | null;
  stage: string | null;
  language: Language | null;
  chunk_count: number;
  /** A free-text label ("Unit 2 — Processes") the student groups files under. */
  module: string | null;
  last_opened_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Stats = {
  subjects: number;
  materials: number;
  materials_ready: number;
};

export type ProviderId = "anthropic" | "gemini" | "openai" | "groq";

export type Provider = {
  id: ProviderId;
  label: string;
  models: string[];
  default_model: string;
  key_url: string;
  configured: boolean;
  /** Last four characters of the saved key; the key itself is never sent back. */
  key_hint: string | null;
  model: string | null;
};

export type Conversation = {
  id: string;
  subject_id: string | null;
  title: string;
  provider: string | null;
  model: string | null;
  created_at: string;
  updated_at: string;
  /** What the conversation may search: every course, one course, or chosen files. */
  scope?: "all" | "subject" | "materials";
  material_ids?: string[];
  /** When the list was searched: the piece of the chat that matched. */
  match?: string | null;
};

/** A file attached to a conversation, whose text is read in the background. */
export type ChatAttachment = {
  id: string;
  filename: string;
  kind: "pdf" | "docx" | "image";
  size_bytes: number;
  status: "uploaded" | "processing" | "ready" | "failed";
  error: string | null;
  char_count: number;
  page_count: number | null;
  created_at: string;
};

export type FeedbackReason = "incorrect" | "not_in_materials" | "unclear" | "too_long" | "unsafe" | "other";
export type AnswerFeedback = { rating: "up" | "down"; reason: FeedbackReason | null };

export type Source = {
  n: number;
  material_id: string;
  filename: string;
  page: number | null;
  snippet: string;
};

/** One step an agent took while answering: it started work, or called a tool. */
export type AgentStep = {
  id: number;
  agent: string;
  /** The tool's name, or null for "this agent started". */
  tool: string | null;
  summary: string;
  status: "running" | "waiting" | "done" | "failed" | "blocked";
  ms?: number;
};

/** Which agents the orchestrator chose for a message. */
export type AgentRoute = { agents: string[]; reason: string; shortcut: boolean; ms?: number };

export type QuizBasis = "notes" | "general" | "revision";

/** An event as the calendar server reports it. */
export type CalendarEventView = {
  id?: string | null;
  summary: string;
  day: string;
  start_time: string;
  minutes: number;
  all_day: boolean;
  link?: string | null;
};

/** What a proposal would put on the calendar (the fields a student may edit). */
export type CalendarEventDraft = {
  summary: string;
  description: string;
  day: string;
  start_time: string;
  minutes: number;
  all_day: boolean;
  timezone: string;
};

export type CalendarProposalStatus = "pending" | "approved" | "rejected" | "failed" | "expired";

export type CalendarProposal = {
  proposal_id: string;
  run_id: string;
  action: "add" | "move" | "remove";
  editable: boolean;
  status: CalendarProposalStatus;
  event: CalendarEventDraft;
  before?: CalendarEventDraft;
  event_id?: string;
  result?: CalendarEventView;
  error?: string;
};

/** What the student may change before approving. Only the fields sent are changed. */
export type CalendarEdits = Partial<Pick<CalendarEventDraft, "summary" | "description" | "day" | "start_time" | "minutes">>;

/** A rich card an agent shows in the chat. Unknown kinds are ignored by the screen. */
export type ChatCard =
  | { kind: "quiz"; data: { quiz_id: string; title: string; basis: QuizBasis; count: number; topic: string | null; subject: string | null } }
  | { kind: "quiz_attempt"; data: { quiz_id: string; attempt_id: string } }
  | { kind: "materials"; data: { items: { id: string; filename: string; subject: string; status: string; kind: string }[]; total: number } }
  | { kind: "material"; data: { id: string; filename: string; subject: string } }
  | { kind: "exam"; data: { id: string; title: string; exam_on: string; days_left: number; subject: string | null } }
  | {
      kind: "plan";
      data: {
        today: string;
        total: number;
        items: { id: string; day: string; title: string; minutes: number; status: string; subject: string | null }[];
      };
    }
  | { kind: "assignment"; data: { id: string; title: string; status: string; subject: string | null; due_at: string | null } }
  | { kind: "assignment_run"; data: { assignment_id: string; run_id: string; kind: string; title: string } }
  | { kind: "calendar_proposal"; data: CalendarProposal }
  | { kind: "calendar_events"; data: { start: string; end: string; events: CalendarEventView[] } }
  | { kind: "calendar_connect"; data: { reason: "not_connected" | "reconnect" } };

/** One stored piece of a chat message. */
export type Block =
  | { type: "text"; text: string }
  | { type: "sources"; items: Source[] }
  | { type: "error"; code: string }
  | { type: "stopped" }
  | { type: "steps"; items: AgentStep[]; route: AgentRoute | null }
  | { type: "followups"; items: string[] }
  | { type: "choices"; question: string; options: string[] }
  | ({ type: "card" } & ChatCard);

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  blocks: Block[];
  created_at: string;
  feedback?: AnswerFeedback | null;
  /** The earlier answer this one replaced, when the student asked for it again. */
  replaces_id?: string | null;
};

export type ConversationDetail = Conversation & { messages: ChatMessage[] };

/** Events streamed while an answer is being written. */
export type ChatEvent =
  | { event: "meta"; data: { conversation_id: string; user_message_id?: string; title?: string; provider?: string; model?: string; run_id?: string } }
  | { event: "sources"; data: { items: Source[]; degraded: boolean } }
  | { event: "route"; data: AgentRoute }
  | { event: "step"; data: AgentStep }
  | { event: "token"; data: { text: string; turn?: number } }
  | { event: "discard"; data: { turn: number } }
  | { event: "card"; data: ChatCard }
  | { event: "card_update"; data: Partial<CalendarProposal> & { proposal_id: string } }
  | { event: "safety"; data: { text: string; changes: string[] } }
  | {
      event: "final";
      data: {
        text: string;
        followups: string[];
        choices: { question: string; options: string[] } | null;
        diagrams_refused: number;
        citations_removed: number[];
      };
    }
  | {
      event: "done";
      data: {
        message_id: string | null;
        awaiting_approval?: boolean;
        usage?: { prompt_tokens: number; completion_tokens: number };
        /** The id of the answer this one replaced (written again). */
        replaces?: string | null;
      };
    }
  | { event: "error"; data: { code: string; message_id: string | null } };

// ---- Evaluation Lab -------------------------------------------------------------------------

export type EvalMode = "baseline" | "hybrid" | "advanced";
export type EvalStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type EvalDataset = {
  id: string;
  name: string;
  description: string | null;
  subject_id: string | null;
  subject_name: string | null;
  cases: number;
  unanswerable: number;
  languages: Record<string, number>;
  created_at: string;
};

export type EvidenceItem = { phrase: string; file?: string | null; page?: number | null };

export type EvalCase = {
  id: string;
  key: string;
  language: Language;
  question: string;
  reference_answer: string | null;
  answerable: boolean;
  evidence: EvidenceItem[];
  tags: string[];
};

export type EvalDatasetDetail = EvalDataset & { items: EvalCase[] };

export type EvalSummary = {
  cases: number;
  failed: number;
  degraded: number;
  answerable: number;
  unanswerable: number;
  metrics: Record<string, number>;
  by_language: Record<string, { cases: number; metrics: Record<string, number> }>;
  latency: Record<string, number | null>;
  est_tokens_avg: number | null;
};

export type EvalRunConfig = {
  mode: EvalMode;
  top_k: number;
  candidates: number;
  generate: boolean;
  judge: boolean;
  provider: string | null;
  model: string | null;
};

export type EvalRun = {
  id: string;
  dataset_id: string;
  dataset_name: string | null;
  label: string | null;
  config: EvalRunConfig;
  status: EvalStatus;
  total: number;
  done: number;
  summary: EvalSummary | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type EvalRetrieved = {
  n: number;
  filename: string;
  page: number | null;
  score: number;
  relevant: boolean;
  text: string;
};

export type EvalResult = {
  case_key: string;
  language: Language;
  question: string;
  reference_answer: string | null;
  answerable: boolean;
  retrieved: EvalRetrieved[];
  answer: string | null;
  scores: Record<string, number>;
  timings: Record<string, number>;
  error: string | null;
};

export type EvalCheck = {
  materials: string[];
  chunks: number;
  ok: number;
  missing: number;
  cases: {
    key: string;
    language: Language;
    answerable: boolean;
    ok: boolean;
    evidence: { phrase: string; file: string | null; found: boolean }[];
  }[];
};

// ------------------------------------------------------------------ quizzes and revision

export type QuizType = "mcq" | "true_false" | "short";
export type QuizStatus = "queued" | "generating" | "ready" | "failed";
/** The one status a quiz is shown with everywhere (worked out by the API). */
export type QuizDisplayStatus = "ready" | "in_progress" | "completed" | "archived" | "preparing" | "failed";
export type AttemptStatus = "in_progress" | "grading" | "completed";

export type AttemptBrief = {
  id: string;
  status: AttemptStatus;
  points: number;
  total: number;
  unscored: number;
  percent: number | null;
  finished_at: string | null;
};

export type Quiz = {
  id: string;
  title: string;
  source: "subject" | "revision";
  subject_id: string | null;
  subject_name: string | null;
  language: Language;
  status: QuizStatus;
  error: string | null;
  question_count: number;
  config: Record<string, unknown>;
  created_at: string;
  attempts: number;
  last_attempt: AttemptBrief | null;
  /** The best finished score (0..1), and the attempt still open, if any. */
  best_percent: number | null;
  open_attempt_id: string | null;
  /** Default time limit for attempts, in minutes (null: untimed). */
  time_limit_minutes: number | null;
  display_status: QuizDisplayStatus;
  archived_at: string | null;
  /** How many generated questions were thrown away by the quality checks. */
  rejected_count: number;
};

export type QuizQuestion = {
  id: string;
  position: number;
  qtype: QuizType;
  prompt: string;
  options: string[] | null;
};

export type QuizDetail = Quiz & {
  questions: QuizQuestion[];
};

export type AttemptStart = { id: string; quiz_id: string; status: AttemptStatus };

export type QuizResult = {
  question_id: string;
  position: number;
  qtype: QuizType;
  prompt: string;
  options: string[] | null;
  answer: string;
  explanation: string | null;
  source: { filename?: string; page?: number | null; text?: string } | null;
  response: string;
  score: number | null;
  feedback: string | null;
};

export type Attempt = {
  id: string;
  quiz_id: string;
  quiz_title: string;
  language: Language;
  status: AttemptStatus;
  points: number;
  total: number;
  unscored: number;
  percent: number | null;
  started_at: string;
  submitted_at: string | null;
  finished_at: string | null;
  results: QuizResult[];
};

export type QuizProgress = {
  attempts: number;
  average: number | null;
  subjects: { subject_id: string | null; name: string | null; attempts: number; average: number | null }[];
  recent: { attempt_id: string; quiz_id: string; title: string; percent: number | null; finished_at: string | null }[];
  revision: {
    cards: number;
    due: number;
    next_due_at: string | null;
    boxes: Record<string, number>;
    due_by_subject: { subject_id: string | null; name: string | null; due: number }[];
  };
};

// ------------------------------------------------------------------ assignments

export type AssignmentStatus = "todo" | "in_progress" | "done";
export type HelpKind = "breakdown" | "outline" | "feedback";
export type RunStatus = "queued" | "running" | "ready" | "failed";

export type RunBrief = { kind: HelpKind; id: string; status: RunStatus };

export type Assignment = {
  id: string;
  title: string;
  subject_id: string | null;
  subject_name: string | null;
  due_at: string | null;
  status: AssignmentStatus;
  has_brief: boolean;
  has_draft: boolean;
  updated_at: string;
  runs: RunBrief[];
  has_rubric: boolean;
  rubric_points: number;
  file_count: number;
  word_count: number;
  last_activity_at: string | null;
};

export type RunSource = { n: number; filename: string; page: number | null; material_id: string };

export type AssignmentRun = {
  id: string;
  kind: HelpKind;
  language: Language;
  status: RunStatus;
  error: string | null;
  result: string | null;
  sources: RunSource[];
  created_at: string;
  finished_at: string | null;
  /** The saved version of the draft a feedback run was about. */
  revision_id: string | null;
};

export type RubricCriterion = { id: string; title: string; points: number; descriptor: string };
export type Rubric = { criteria: RubricCriterion[]; total: number };

export type AssignmentFile = {
  id: string;
  filename: string;
  mime_type: string | null;
  size_bytes: number | null;
  status: MaterialStatus;
  error: string | null;
  created_at: string;
};

export type RevisionSource = "auto" | "manual" | "restore" | "feedback" | "baseline";
export type Revision = {
  id: string;
  source: RevisionSource;
  note: string;
  word_count: number;
  created_at: string;
  updated_at: string;
};
export type RevisionWithBody = Revision & { body: string };

export type AssignmentDetail = Assignment & {
  brief: string;
  draft: string;
  latest_runs: AssignmentRun[];
  rubric: Rubric | null;
  files: AssignmentFile[];
  revision_count: number;
};

// ------------------------------------------------------------------ planner and calendar

export type TaskStatus = "todo" | "done" | "cancelled" | "skipped";
/** What the student is shown, worked out by the server from the status and the day. */
export type TaskState = "pending" | "completed" | "overdue" | "cancelled";

export type StudyTask = {
  id: string;
  kind: "revise" | "assignment" | "quiz" | "custom";
  source: "plan" | "manual";
  title: string;
  template: string | null;
  params: Record<string, string | number>;
  planned_for: string;
  minutes: number;
  status: TaskStatus;
  state: TaskState;
  /** A planner task the student moved or resized: making the plan again leaves it alone. */
  pinned: boolean;
  subject_id: string | null;
  subject_name: string | null;
  assignment_id: string | null;
  exam_id: string | null;
};

export type Overload = {
  day: string;
  minutes: number;
  limit: number;
  excess: number;
  day_off: boolean;
  suggested: string | null;
};

export type TasksResponse = {
  today: string;
  daily_minutes: number;
  days_off: number[];
  items: StudyTask[];
  overload: Overload[];
};

export type Exam = {
  id: string;
  title: string;
  exam_on: string;
  subject_id: string | null;
  subject_name: string | null;
  notes: string;
  days_left: number;
};

export type StudyPreferences = { daily_minutes: number; days_off: number[] };

export type GenerateResult = {
  created: number;
  first_day: string;
  last_day: string;
  notice: "nothing_to_plan" | "up_to_date" | null;
  kept: number;
  already_handled: number;
};

export type CalendarEvent = {
  kind: "assignment" | "exam" | "task" | "revision" | "event";
  day: string;
  id: string | null;
  title: string;
  status: string | null;
  minutes: number | null;
  count: number | null;
  template: string | null;
  params: Record<string, string | number> | null;
  subject_name: string | null;
  subject_id: string | null;
  /** Tasks: what they belong to and who made them. Assignments: the exact due time. */
  assignment_id: string | null;
  exam_id: string | null;
  source: "plan" | "manual" | null;
  due_at: string | null;
  /** Tasks: pending | completed | overdue | cancelled. */
  state: TaskState | null;
  /** The student's own events: time of day ("" = all day), notes, and whether it goes to Google. */
  start_time: string | null;
  notes: string | null;
  sync_to_google: boolean | null;
  /** On Google Calendar? Null when Google is not connected or the item is not meant for it. */
  sync: SyncState | null;
};

export type SyncState = "synced" | "pending" | "failed";

/** An event the student added to their calendar. */
export type OwnEvent = {
  id: string;
  title: string;
  notes: string;
  day: string;
  start_time: string;
  minutes: number;
  subject_id: string | null;
  subject_name: string | null;
  sync_to_google: boolean;
  sync: SyncState | null;
};

export type CalendarResponse = { today: string; events: CalendarEvent[] };

export type GoogleEvent = {
  id: string;
  summary: string;
  day: string;
  start_time: string;
  minutes: number;
  all_day: boolean;
  link: string;
};
export type GoogleEventsResponse = { connected: boolean; error: string | null; events: GoogleEvent[] };

export type GcalStatus = {
  available: boolean;
  connected: boolean;
  needs_reconnect: boolean;
  connected_at: string | null;
  last_synced_at: string | null;
  synced_items: number;
};

export type GcalAction = "create" | "update" | "delete";
export type GcalSource = "exam" | "assignment" | "task" | "event";

export type GcalChange = {
  action: GcalAction;
  source_type: GcalSource;
  source_id: string;
  day: string;
  summary: string;
};

/** What is waiting to be sent to Google or failed, with the reason. */
export type GcalSyncItem = {
  source_type: GcalSource;
  source_id: string;
  state: "pending" | "failed";
  action: GcalAction;
  day: string;
  summary: string;
  error: string | null;
  attempts: number;
  last_failed_at: string | null;
};

export type GcalState = { synced: number; pending: number; failed: number; items: GcalSyncItem[] };

export type GcalSyncResult = {
  created: number;
  updated: number;
  deleted: number;
  failed: { source_type: GcalSource; source_id: string; error: string }[];
};

export type GroupRole = "owner" | "admin" | "member";
export type Group = {
  id: string;
  name: string;
  description: string;
  role: GroupRole;
  member_count: number;
  item_count: number;
  join_code: string | null;
  created_at: string;
};
export type GroupPerson = {
  user_id: string;
  display_name: string;
  role: GroupRole;
  joined_at: string;
  is_me: boolean;
};
export type GroupDetail = Group & { members: GroupPerson[] };

export type GroupInvitation = {
  id: string;
  email: string;
  role: "admin" | "member";
  invited_by_name: string | null;
  created_at: string;
  expires_at: string;
};
export type MyInvitation = {
  id: string;
  group_id: string;
  group_name: string;
  group_description: string;
  role: "admin" | "member";
  invited_by_name: string;
  created_at: string;
  expires_at: string;
};
export type GroupNoteSummary = {
  id: string;
  title: string;
  excerpt: string;
  pinned: boolean;
  author_id: string;
  /** null: the author has left the group. */
  author_name: string | null;
  mine: boolean;
  can_change: boolean;
  created_at: string;
  updated_at: string;
};
export type GroupNote = GroupNoteSummary & { body: string };
export type GroupThreadSummary = {
  id: string;
  title: string;
  excerpt: string;
  pinned: boolean;
  locked: boolean;
  author_id: string;
  author_name: string | null;
  mine: boolean;
  reply_count: number;
  created_at: string;
  last_activity_at: string;
};
export type GroupPost = {
  id: string;
  body: string;
  author_id: string;
  author_name: string | null;
  mine: boolean;
  can_edit: boolean;
  can_delete: boolean;
  created_at: string;
  edited_at: string | null;
};
export type GroupThread = GroupThreadSummary & {
  body: string;
  edited_at: string | null;
  can_edit: boolean;
  can_delete: boolean;
  can_moderate: boolean;
  posts: GroupPost[];
};
export type Rsvp = "going" | "maybe" | "declined";
export type GroupSession = {
  id: string;
  title: string;
  description: string;
  starts_at: string;
  minutes: number;
  location: string;
  status: "scheduled" | "cancelled";
  state: "upcoming" | "ongoing" | "past" | "cancelled";
  created_by: string;
  created_by_name: string | null;
  mine: boolean;
  can_change: boolean;
  going: number;
  maybe: number;
  declined: number;
  my_response: Rsvp | null;
  attendees: { user_id: string; name: string; response: Rsvp }[];
};
export type CalendarAdded = { event_id: string; day: string; start_time: string; already: boolean };
export type SharedItem = {
  id: string;
  filename: string;
  kind: MaterialKind;
  mime_type: string | null;
  size_bytes: number | null;
  note: string;
  status: "active" | "hidden";
  shared_by_name: string;
  mine: boolean;
  course_name: string | null;
  author: string;
  institution: string;
  rights: ShareRights;
  can_remove: boolean;
  can_report: boolean;
  reported_by_me: boolean;
  reports: number | null;
  created_at: string;
};
export type ShareRights = "own_work" | "permitted" | "open_licence";
export type Shareable = { id: string; filename: string; kind: MaterialKind; size_bytes: number | null; subject_name: string };
export type ReportReason = "copyright" | "inappropriate" | "wrong_content" | "other";

export type AdminOverview = {
  totals: Record<string, number>;
  series: { day: string; signups: number; active_users: number }[];
};
export type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  status: "active" | "suspended";
  email_verified: boolean;
  is_admin: boolean;
  has_google: boolean;
  created_at: string;
  last_seen_at: string | null;
  subjects: number;
  materials: number;
  storage_bytes: number;
  messages_30d: number;
};
export type AdminUsers = { items: AdminUser[]; total: number };
export type AdminReport = {
  item_id: string;
  group_id: string;
  group_name: string;
  filename: string;
  kind: string;
  size_bytes: number | null;
  status: "active" | "hidden";
  shared_by_name: string;
  shared_by_email: string;
  reports: number;
  last_report_at: string | null;
  reasons: Record<string, number>;
  notes: string[];
  created_at: string;
};
export type AdminSecurityRow = { kind: string; events: number; students: number };
export type AdminAuditRow = {
  id: string;
  admin_name: string | null;
  action: string;
  target_email: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

// ------------------------------------------------------------------ dashboard, notifications, search

export type DashCourse = {
  id: string;
  name: string;
  course_code: string | null;
  semester: string | null;
  documents: number;
  documents_ready: number;
  past_papers: number;
  notes: number;
  quiz_attempts: number;
  quiz_average: number | null;
  last_activity_at: string | null;
  next_exam_title: string | null;
  next_exam_on: string | null;
  next_exam_days: number | null;
  chats: number;
};

export type ScheduleTask = {
  id: string;
  title: string;
  minutes: number;
  status: "todo" | "done" | "skipped" | "cancelled";
  kind: string;
  subject_id: string | null;
  subject_name: string | null;
  /** The one shared state (pending | completed | overdue | cancelled), worked out by the API. */
  state?: "pending" | "completed" | "overdue" | "cancelled";
  planned_for?: string | null;
  href?: string;
};

export type WeekDay = {
  date: string;
  minutes_planned: number;
  minutes_done: number;
  tasks: number;
  day_off: boolean;
  markers: { kind: "exam" | "assignment"; title: string }[];
};

export type RecentDocument = {
  id: string;
  filename: string;
  kind: MaterialKind;
  status: MaterialStatus;
  subject_id: string;
  subject_name: string;
  module: string | null;
  at: string;
  reason: "opened" | "added";
};

export type AssignmentDue = {
  id: string;
  title: string;
  subject_name: string | null;
  status: string;
  due_on: string;
  days_left: number;
};

export type ActivityItem = {
  kind: "chat" | "quiz" | "material" | "task" | "assignment";
  title: string;
  detail: string | null;
  subject_name: string | null;
  at: string;
  href: string;
};

export type DashboardData = {
  course: DashCourse | null;
  daily_minutes: number;
  schedule: ScheduleTask[];
  week: WeekDay[];
  recent_documents: RecentDocument[];
  assignments_due: AssignmentDue[];
  activity: ActivityItem[];
  today: string;
  stats: {
    subjects: number;
    materials: number;
    materials_ready: number;
    quiz_attempts: number;
    quiz_average: number | null;
    revision_due: number;
    conversations: number;
  };
  streak_days: number;
  today_tasks: { total: number; done: number; minutes_total: number; minutes_done: number };
  subjects: {
    id: string;
    name: string;
    course_code: string | null;
    semester: string | null;
    materials: number;
    materials_ready: number;
    quiz_attempts: number;
    quiz_average: number | null;
  }[];
  study_week: { date: string; minutes_done: number; minutes_planned: number }[];
  quiz_trend: { attempt_id: string; quiz_id: string; title: string; percent: number; finished_at: string | null }[];
  weak_topics: { subject_id: string; subject_name: string; material: string; accuracy: number; answers: number }[];
  deadlines: {
    kind: "exam" | "assignment";
    id: string;
    title: string;
    subject_name: string | null;
    on: string;
    days_left: number;
  }[];
  recent_chats: { id: string; title: string; updated_at: string }[];
  scope?: "all" | "course";
  /** The same figures as `course`, for every course together (what the page shows when no course is chosen). */
  overview?: {
    courses: number;
    documents: number;
    documents_ready: number;
    past_papers: number;
    notes: number;
    quiz_attempts: number;
    quiz_average: number | null;
    chats: number;
    last_activity_at: string | null;
    next_exam_title: string | null;
    next_exam_on: string | null;
    next_exam_days: number | null;
  } | null;
  /** Tasks in the schedule by shared state (pending, completed, overdue, cancelled). */
  task_states?: Record<string, number>;
  /** The getting-started checklist, from the student's real data. */
  setup?: { show: boolean; done: number; total: number; steps: { key: string; done: boolean; href: string }[] } | null;
};

export type NotificationKind =
  | "exam_soon"
  | "assignment_due"
  | "assignment_overdue"
  | "revision_due"
  | "material_failed"
  | "calendar_reconnect"
  | "tasks_today";

export type AppNotification = {
  key: string;
  kind: NotificationKind;
  severity: "info" | "warning" | "danger";
  params: Record<string, string | number>;
  href: string;
  read: boolean;
};

export type SearchHit = { id: string; title: string; detail: string | null; href: string };

export type SearchResults = {
  query: string;
  subjects: SearchHit[];
  materials: SearchHit[];
  quizzes: SearchHit[];
  assignments: SearchHit[];
  conversations: SearchHit[];
  exams: SearchHit[];
};

// ---- Materials Library ------------------------------------------------------------------

export type LibraryScope = "college" | "others" | "global" | "mine";
export type LibraryDocType = "notes" | "past_paper" | "textbook" | "slides" | "reference" | "other";
export type LibraryVisibility = "private" | "institution" | "public";
export type LibraryStatus = "draft" | "pending_review" | "published" | "rejected" | "held" | "taken_down";

export type LibraryItem = {
  id: string;
  title: string;
  description: string;
  doc_type: LibraryDocType;
  course_name: string;
  topic: string;
  semester: string;
  academic_year: string;
  author: string;
  institution: string;
  rights: ShareRights;
  visibility: LibraryVisibility;
  status: LibraryStatus;
  /** Why a moderator turned it down; only the owner receives it. */
  review_note: string;
  filename: string;
  mime_type: string | null;
  size_bytes: number | null;
  previewable: boolean;
  mine: boolean;
  reported_by_me: boolean;
  published_at: string | null;
  created_at: string;
};

export type LibraryPage = { items: LibraryItem[]; total: number; my_institution: string };

export type LibraryFacets = {
  courses: string[];
  topics: string[];
  semesters: string[];
  years: string[];
  institutions: string[];
};

export type LibraryQueueRow = {
  id: string;
  title: string;
  filename: string;
  doc_type: LibraryDocType;
  visibility: LibraryVisibility;
  status: LibraryStatus;
  rights: ShareRights;
  institution: string;
  author: string;
  owner_name: string;
  reports: number;
  reasons: ReportReason[];
  notes: string[];
  imports: number;
  created_at: string;
};

// ---- Local retrieval models ---------------------------------------------------------------

export type ModelPart = { name: string; loaded: boolean | null; device: string | null };

export type ModelsStatus = {
  reachable: boolean;
  problem: "unreachable" | "unsupported" | "bad_response" | null;
  checked_at: string;
  latency_ms: number | null;
  service: string;
  backend: string | null;
  embedding: ModelPart | null;
  reranker: ModelPart | null;
  dim: number | null;
  expected_dim: number;
  dim_matches: boolean | null;
  cuda_available: boolean | null;
  gpu_name: string | null;
  precision: string | null;
  max_seq_length: number | null;
  embed_batch_size: number | null;
  rerank_batch_size: number | null;
  modes: string[];
  rerank_chars: number;
  rrf_k: number;
};
