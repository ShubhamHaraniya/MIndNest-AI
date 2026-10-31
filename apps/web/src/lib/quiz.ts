import type { MessageKey, TFunction } from "@/i18n/translate";

import { ApiError, api } from "./api";
import { errorMessage, llmErrorText } from "./errors";
import type { AttemptStart, AttemptStatus, Language, QuizStatus, QuizType } from "./types";

export const QUESTION_TYPES: QuizType[] = ["mcq", "true_false", "short"];
export const DIFFICULTIES = ["easy", "medium", "hard"] as const;
export const QUIZ_LANGUAGES: Language[] = ["en", "hi", "gu"];
export const MIN_QUESTIONS = 3;
export const MAX_QUESTIONS = 20;
export const MAX_RESPONSE_CHARS = 1000;
/** Time limits offered when a quiz is made or an attempt is started, in minutes (0 = none). */
export const TIME_LIMITS = [0, 10, 15, 20, 30, 45, 60, 90, 120] as const;
/** Below this score a topic is worth revising (the dashboard uses the same line). */
export const WEAK_BELOW = 0.8;

export function isWriting(status: QuizStatus): boolean {
  return status === "queued" || status === "generating";
}

/** 0..1 as a whole percentage; "–" when there is nothing to show. */
export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(value * 100)}%`;
}

/** Whole numbers plainly, halves with one decimal ("2.5"). */
export function formatPoints(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** "12:05" or "1:02:05" for a clock face. */
export function formatClock(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const two = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
}

/** "34 min" / "1 h 05 min" / "40 s" for a time taken. */
export function formatTaken(seconds: number | null | undefined, t: TFunction): string {
  if (seconds === null || seconds === undefined) return "–";
  if (seconds < 60) return t("qz.sec", { n: Math.max(1, Math.round(seconds)) });
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return t("qz.min", { n: minutes });
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? t("qz.hour", { n: h }) : `${t("qz.hour", { n: h })} ${t("qz.min", { n: m })}`;
}

const FAILURES: Record<string, MessageKey> = {
  no_materials: "quiz.fail.no_materials",
  generation_failed: "quiz.fail.generation_failed",
  unknown_provider: "quiz.fail.unknown_provider",
  internal: "quiz.fail.internal",
  no_provider_key: "errors.no_provider_key",
  key_unreadable: "errors.key_unreadable",
};

/** Why a quiz could not be written, in the student's language. */
export function failureText(code: string | null, t: TFunction): string {
  if (code && FAILURES[code]) return t(FAILURES[code]);
  return llmErrorText(code ?? "", t);
}

const QUIZ_ERRORS: Record<string, MessageKey> = {
  time_up: "qz.err.time_up",
  nothing_missed: "qz.err.nothing_missed",
  not_failed: "qz.err.not_failed",
  attempt_in_progress: "qz.err.attempt_in_progress",
  quiz_archived: "qzx.err.archived",
};

/** A message for a failed request, including the errors only quizzes can raise. */
export function quizError(error: unknown, t: TFunction): string {
  if (error instanceof ApiError && QUIZ_ERRORS[error.code]) return t(QUIZ_ERRORS[error.code]);
  return errorMessage(error, t);
}

/** Start (or resume) an attempt and return its id. `limitMinutes` sets the time limit of a new
 *  attempt (0 = none); leave it out to use the quiz's own default. */
export async function beginAttempt(quizId: string, limitMinutes?: number): Promise<string> {
  const attempt = await api<AttemptStart>(`/quizzes/${quizId}/attempts`, {
    method: "POST",
    body: limitMinutes === undefined ? undefined : { time_limit_minutes: limitMinutes },
  });
  return attempt.id;
}

export function typeLabelKey(type: QuizType): MessageKey {
  return `quiz.type.${type}` as MessageKey;
}

export type Verdict = "correct" | "partial" | "wrong" | "pending" | "unmarked";

export function verdictOf(score: number | null, waiting: boolean): Verdict {
  if (score === null) return waiting ? "pending" : "unmarked";
  if (score >= 0.99) return "correct";
  return score > 0 ? "partial" : "wrong";
}

/** The label for a multiple-choice letter: 0 -> A. */
export function optionLetter(index: number): string {
  return String.fromCharCode(65 + index);
}

// ------------------------------------------------------------------ exam and analysis shapes

export type ExamQuestion = {
  id: string;
  position: number;
  qtype: QuizType;
  prompt: string;
  options: string[] | null;
};

export type ExamSession = {
  attempt_id: string;
  quiz_id: string;
  title: string;
  subject_id: string | null;
  subject_name: string | null;
  language: Language;
  status: AttemptStatus;
  started_at: string;
  server_now: string;
  limit_seconds: number | null;
  remaining_seconds: number | null;
  questions: ExamQuestion[];
  answers: Record<string, string>;
  flags: string[];
};

export type DraftResult = { saved: number; server_now: string; remaining_seconds: number | null };

export type QuestionInsight = {
  question_id: string;
  position: number;
  score: number | null;
  topic: string | null;
  material_id: string | null;
  card: { box: number; due_at: string; times_seen: number; times_correct: number } | null;
};

export type TopicStat = {
  topic: string | null;
  material_id: string | null;
  module: string | null;
  answers: number;
  points: number;
  accuracy: number | null;
  missed: number;
  earlier_answers: number;
  earlier_accuracy: number | null;
  cards: number;
  cards_due: number;
};

export type HistoryPoint = {
  attempt_id: string;
  status: AttemptStatus;
  points: number;
  total: number;
  unscored: number;
  percent: number | null;
  started_at: string;
  submitted_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
};

export type Analysis = {
  attempt_id: string;
  quiz_id: string;
  quiz_title: string;
  source: "subject" | "revision";
  status: AttemptStatus;
  started_at: string;
  submitted_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  limit_seconds: number | null;
  points: number;
  total: number;
  unscored: number;
  percent: number | null;
  missed: number;
  questions: QuestionInsight[];
  topics: TopicStat[];
  history: HistoryPoint[];
  course: {
    subject_id: string;
    name: string;
    attempts: number;
    average: number | null;
    best: number | null;
    cards_due: number;
  } | null;
  revision: { cards: number; due_now: number; next_due_at: string | null };
};

/** A signed difference between two 0..1 scores, in percentage points ("+12", "-5", "0"). */
export function pointsDelta(now: number | null, before: number | null): string | null {
  if (now === null || before === null) return null;
  const diff = Math.round((now - before) * 100);
  return diff > 0 ? `+${diff}` : String(diff);
}
