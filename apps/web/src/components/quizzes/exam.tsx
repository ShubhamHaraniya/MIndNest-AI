"use client";

import clsx from "clsx";
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Clock, Flag, Loader2, X } from "lucide-react";
import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Dialog } from "@/components/dialog";
import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { Textarea } from "@/components/kit/controls";
import { AnimatedRing } from "@/components/motion/ring";
import { INLINE_MD, QuizMarkdown } from "@/components/quizzes/parts";
import { useExamClock, useExamDraft, type SaveState } from "@/components/quizzes/use-exam";
import { useLocale, useT } from "@/i18n/client";
import type { TFunction } from "@/i18n/translate";
import { ApiError, api } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { MAX_RESPONSE_CHARS, formatClock, optionLetter, quizError, typeLabelKey, type ExamQuestion, type ExamSession } from "@/lib/quiz";
import type { Attempt } from "@/lib/types";

type Phase = "taking" | "submitting" | "timeup";

const isAnswered = (answers: Record<string, string>, id: string) => (answers[id] ?? "").trim() !== "";

/** A question prompt as one plain line, for lists in the review screen. */
function plain(prompt: string): string {
  return prompt.replace(/```[\s\S]*?```/g, " (code) ").replace(/[`*_$\\{}]/g, "").replace(/\s+/g, " ").trim().slice(0, 110);
}

/** The exam: a focused full-screen layout with a timer, a question navigator, one question at a
 *  time, autosave, a review screen and a confirmed submit. */
export function ExamView({
  session,
  onSubmitted,
  onReload,
}: {
  session: ExamSession;
  onSubmitted: (attempt: Attempt) => void;
  onReload: () => void;
}) {
  const t = useT();
  const router = useRouter();
  const questions = session.questions;
  const draft = useExamDraft(session);
  const { elapsed, remaining } = useExamClock(session);
  const [index, setIndex] = useState(0);
  const [phase, setPhase] = useState<Phase>("taking");
  const [reviewing, setReviewing] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fired = useRef(false);

  const question = questions[index];
  const answered = questions.filter((candidate) => isAnswered(draft.answers, candidate.id)).length;
  const unanswered = questions.length - answered;
  const locked = phase !== "taking";

  const submit = useCallback(
    async (answers: Record<string, string>) => {
      setError(null);
      setPhase((current) => (current === "timeup" ? current : "submitting"));
      try {
        const done = await api<Attempt>(`/attempts/${session.attempt_id}/submit`, {
          method: "POST",
          body: {
            answers: questions.map((candidate) => ({ question_id: candidate.id, response: (answers[candidate.id] ?? "").trim() })),
          },
        });
        draft.finish();
        onSubmitted(done);
      } catch (caught) {
        if (caught instanceof ApiError && caught.code === "already_submitted") {
          draft.finish();
          onReload();
          return;
        }
        setError(quizError(caught, t));
        setPhase((current) => (current === "timeup" ? current : "taking"));
      }
    },
    // `draft` changes identity on every answer, but `finish` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [session.attempt_id, questions, onSubmitted, onReload, t, draft.finish],
  );

  // Time is up: close the questions and send what the student has.
  const answersRef = useRef(draft.answers);
  answersRef.current = draft.answers;
  useEffect(() => {
    if (remaining === null || remaining > 0 || fired.current) return;
    fired.current = true;
    setReviewing(false);
    setPhase("timeup");
    void submit(answersRef.current);
  }, [remaining, submit]);

  // Spoken warnings as the limit gets close.
  const [notice, setNotice] = useState("");
  const warned = useRef(new Set<number>());
  useEffect(() => {
    if (remaining === null) return;
    for (const mark of [300, 60, 10]) {
      if (remaining <= mark && !warned.current.has(mark)) {
        warned.current.add(mark);
        setNotice(t("qz.exam.timeWarning", { time: formatClock(remaining) }));
      }
    }
  }, [remaining, t]);

  const go = useCallback(
    (next: number) => setIndex(Math.max(0, Math.min(questions.length - 1, next))),
    [questions.length],
  );

  // Keyboard: arrows move, F flags, numbers jump, A-D choose a multiple-choice option.
  const keys = useRef({ digits: "", timer: 0 });
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || locked || reviewing || leaving) return;
      const target = event.target as HTMLElement | null;
      if (target && target.closest("textarea, input[type='text'], input[type='search'], select, [contenteditable='true']")) return;
      const current = questions[index];
      if (!current) return;
      if (event.key === "ArrowRight") {
        event.preventDefault();
        go(index + 1);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        go(index - 1);
      } else if (event.key === "f" || event.key === "F") {
        event.preventDefault();
        draft.toggleFlag(current.id);
      } else if (/^[0-9]$/.test(event.key)) {
        window.clearTimeout(keys.current.timer);
        let wanted = Number(keys.current.digits + event.key);
        keys.current.digits = wanted >= 1 && wanted <= questions.length ? keys.current.digits + event.key : event.key;
        wanted = Number(keys.current.digits);
        if (wanted >= 1 && wanted <= questions.length) go(wanted - 1);
        if (keys.current.digits.length >= String(questions.length).length) keys.current.digits = "";
        keys.current.timer = window.setTimeout(() => (keys.current.digits = ""), 800);
      } else if (current.qtype === "mcq" && /^[a-dA-D]$/.test(event.key)) {
        const choice = event.key.toLowerCase().charCodeAt(0) - 97;
        if (choice < (current.options?.length ?? 0)) draft.setAnswer(current.id, String(choice));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [questions, index, locked, reviewing, leaving, go, draft]);

  if (!question) return null;
  const flagged = draft.flags.includes(question.id);
  const low = remaining !== null && remaining <= 60;
  const warn = remaining !== null && remaining <= 300;

  return (
    <div
      className="fixed inset-0 z-40 flex flex-col text-ink"
      style={{ background: "radial-gradient(70rem 32rem at 50% -12%, color-mix(in srgb, var(--primary) 16%, var(--bg)), var(--bg) 72%)" }}
    >
      <header className="glass mx-2 mt-2 flex h-14 shrink-0 items-center gap-2 rounded-2xl px-2 sm:mx-4 sm:mt-3 sm:gap-3 sm:px-4">
        <Button variant="ghost" size="sm" onClick={() => setLeaving(true)} disabled={phase === "submitting"} aria-label={t("qz.exam.leave")}>
          <X className="h-4 w-4" aria-hidden />
          <span className="hidden sm:inline">{t("qz.exam.leave")}</span>
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[13px] font-semibold leading-4" title={session.title}>
            {session.title}
          </h1>
          <p className="truncate text-xs leading-4 text-muted">{session.subject_name ?? t("quiz.list.revisionTag")}</p>
        </div>
        <SaveStatus state={draft.state} savedAt={draft.savedAt} t={t} />
        <div
          role="timer"
          aria-label={remaining === null ? t("qz.exam.elapsed") : t("qz.exam.remaining")}
          className={clsx(
            "tabular flex h-10 items-center gap-2 rounded-full border py-1 pl-1 pr-3 text-sm font-medium",
            low ? "border-danger/60 bg-danger-soft text-danger" : warn ? "border-warning/60 bg-warning-soft text-warning" : "border-border-strong bg-surface-2/60",
          )}
        >
          {remaining !== null && session.limit_seconds ? (
            <AnimatedRing
              value={Math.max(0, Math.min(1, remaining / session.limit_seconds))}
              size={32}
              stroke={3.5}
              label={t("qz.exam.remaining")}
              tone={low ? "danger" : warn ? "warning" : "primary"}
            >
              <Clock className="h-3 w-3" aria-hidden />
            </AnimatedRing>
          ) : (
            <span className="flex h-8 w-8 items-center justify-center">
              <Clock className="h-4 w-4" aria-hidden />
            </span>
          )}
          <span>{formatClock(remaining ?? elapsed)}</span>
          <span className="hidden text-xs font-normal opacity-70 md:inline">{remaining === null ? t("qz.exam.elapsed") : t("qz.exam.left")}</span>
        </div>
        <Button size="sm" onClick={() => setReviewing(true)} disabled={locked}>
          {t("qz.exam.review")}
        </Button>
      </header>

      <p className="sr-only" role="status">
        {notice}
      </p>

      {phase === "timeup" ? (
        <div role="alert" className="flex shrink-0 flex-wrap items-center gap-3 border-b border-warning bg-warning-soft px-4 py-2 text-sm text-warning">
          {error ? <AlertTriangle className="h-4 w-4" aria-hidden /> : <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
          <span className="flex-1">{error ?? t("qz.exam.timeUp")}</span>
          {error ? (
            <Button size="sm" onClick={() => void submit(answersRef.current)}>
              {t("common.retry")}
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="glass mx-2 mt-2 shrink-0 rounded-2xl px-3 py-2 sm:mx-4 lg:hidden">
        <div className="mb-1.5 flex items-center justify-between gap-3 text-xs text-muted">
          <span>{t("quiz.take.progress", { done: answered, total: questions.length })}</span>
          {draft.flags.length > 0 ? <span>{t("qz.exam.flaggedCount", { count: draft.flags.length })}</span> : null}
        </div>
        <Navigator questions={questions} answers={draft.answers} flags={draft.flags} index={index} onGo={go} t={t} strip />
      </div>

      <div className="flex min-h-0 flex-1 gap-3 p-2 sm:p-4">
        <main id="exam-main" className="min-w-0 flex-1 overflow-y-auto overscroll-contain" tabIndex={-1}>
          <motion.div
            key={question.id}
            initial={{ opacity: 0, x: 22 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="glass-strong sheen mx-auto w-full max-w-3xl rounded-3xl p-5 sm:p-8"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <span className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">
                  {t("quiz.take.question", { n: index + 1, total: questions.length })}
                </span>
                <Badge>{t(typeLabelKey(question.qtype))}</Badge>
                {flagged ? <Badge tone="warning">{t("qz.exam.flagged")}</Badge> : null}
              </p>
              <Button
                variant={flagged ? "soft" : "ghost"}
                size="sm"
                aria-pressed={flagged}
                disabled={locked}
                onClick={() => draft.toggleFlag(question.id)}
                title={t("qz.exam.flagHint")}
              >
                <Flag className={clsx("h-3.5 w-3.5", flagged && "fill-current")} aria-hidden />
                {flagged ? t("qz.exam.unflag") : t("qz.exam.flag")}
                <kbd className="hidden rounded-sm border border-border-strong px-1 text-[10px] font-normal text-faint sm:inline">F</kbd>
              </Button>
            </div>

            <QuizMarkdown text={question.prompt} className="mt-3 [&_.md-body]:text-[16px] [&_.md-body]:leading-7" />

            <div className="mt-6">
              <AnswerControl
                key={question.id}
                question={question}
                value={draft.answers[question.id] ?? ""}
                disabled={locked}
                onChange={(value) => draft.setAnswer(question.id, value)}
                t={t}
              />
            </div>
          </motion.div>
        </main>

        <aside className="glass hidden w-64 shrink-0 flex-col overflow-y-auto rounded-3xl lg:flex xl:w-72" aria-label={t("qz.exam.navigator")}>
          <div className="px-4 py-3">
            <p className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("qz.exam.navigator")}</p>
            <div className="mt-3 flex items-center gap-3">
              <AnimatedRing
                value={questions.length ? answered / questions.length : 0}
                size={64}
                stroke={6}
                label={t("quiz.take.progress", { done: answered, total: questions.length })}
              >
                <span className="tabular text-sm font-semibold">
                  {answered}/{questions.length}
                </span>
              </AnimatedRing>
              <p className="tabular text-[13px] text-muted">{t("quiz.take.progress", { done: answered, total: questions.length })}</p>
            </div>
          </div>
          <div className="px-4 pb-3">
            <Navigator questions={questions} answers={draft.answers} flags={draft.flags} index={index} onGo={go} t={t} />
          </div>
          <Legend t={t} />
          <div className="mt-auto space-y-3 border-t border-border px-4 py-3">
            <p className="text-xs text-muted">{t("qz.exam.keys")}</p>
            <Button className="w-full" onClick={() => setReviewing(true)} disabled={locked}>
              {t("qz.exam.review")}
            </Button>
          </div>
        </aside>
      </div>

      <footer className="glass mx-2 mb-2 flex h-14 shrink-0 items-center justify-between gap-3 rounded-2xl px-3 sm:mx-4 sm:mb-3 sm:px-4">
        <Button variant="secondary" onClick={() => go(index - 1)} disabled={index === 0 || locked}>
          <ChevronLeft className="h-4 w-4 rtl:rotate-180" aria-hidden />
          {t("quiz.take.previous")}
        </Button>
        <p className="tabular text-xs text-muted">
          {index + 1} / {questions.length}
        </p>
        {index < questions.length - 1 ? (
          <Button onClick={() => go(index + 1)} disabled={locked}>
            {t("common.next")}
            <ChevronRight className="h-4 w-4 rtl:rotate-180" aria-hidden />
          </Button>
        ) : (
          <Button onClick={() => setReviewing(true)} disabled={locked}>
            {t("qz.exam.review")}
          </Button>
        )}
      </footer>

      <ReviewDialog
        open={reviewing}
        onClose={() => setReviewing(false)}
        questions={questions}
        answers={draft.answers}
        flags={draft.flags}
        remaining={remaining}
        busy={phase === "submitting"}
        error={error}
        onJump={(position) => {
          setReviewing(false);
          go(position);
        }}
        onSubmit={() => void submit(draft.answers)}
        unanswered={unanswered}
        t={t}
      />

      <ConfirmDialog
        open={leaving}
        title={t("qz.exam.leaveTitle")}
        description={remaining === null ? t("qz.exam.leaveBody") : t("qz.exam.leaveBodyTimed")}
        confirmLabel={t("qz.exam.leave")}
        tone="primary"
        onConfirm={async () => {
          await draft.flush();
          router.push(`/quizzes/${session.quiz_id}`);
        }}
        onClose={() => setLeaving(false)}
      />
    </div>
  );
}

// ------------------------------------------------------------------------------ small parts

function SaveStatus({ state, savedAt, t }: { state: SaveState; savedAt: number | null; t: TFunction }) {
  const locale = useLocale();
  if (state === "closed") return null;
  const error = state === "error";
  return (
    <p
      className={clsx("hidden items-center gap-1 text-xs sm:flex", error ? "flex text-danger" : "text-muted")}
      role={error ? "alert" : "status"}
      title={savedAt ? formatTime(savedAt, locale) : undefined}
    >
      {state === "saving" ? (
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
      ) : error ? (
        <AlertTriangle className="h-3 w-3" aria-hidden />
      ) : (
        <Check className="h-3 w-3" aria-hidden />
      )}
      <span className={error ? "" : "hidden md:inline"}>{t(error ? "qz.exam.saveError" : state === "saving" ? "qz.exam.saving" : "qz.exam.saved")}</span>
    </p>
  );
}

function Navigator({
  questions,
  answers,
  flags,
  index,
  onGo,
  t,
  strip = false,
}: {
  questions: ExamQuestion[];
  answers: Record<string, string>;
  flags: string[];
  index: number;
  onGo: (index: number) => void;
  t: TFunction;
  strip?: boolean;
}) {
  const current = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (strip) current.current?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [index, strip]);
  return (
    <ol className={strip ? "flex gap-1.5 overflow-x-auto pb-1" : "grid grid-cols-5 gap-1.5"}>
      {questions.map((candidate, position) => {
        const done = isAnswered(answers, candidate.id);
        const marked = flags.includes(candidate.id);
        const here = position === index;
        return (
          <li key={candidate.id} className={strip ? "shrink-0" : ""}>
            <button
              ref={here ? current : undefined}
              type="button"
              onClick={() => onGo(position)}
              aria-label={`${t("quiz.take.goTo", { n: position + 1 })}${done ? `, ${t("qz.exam.answered")}` : ""}${marked ? `, ${t("qz.exam.flagged")}` : ""}`}
              aria-current={here ? "step" : undefined}
              className={clsx(
                "tabular relative h-9 rounded-xl border text-[13px] transition-all",
                strip ? "w-9" : "w-full",
                here ? "scale-105 border-primary font-semibold ring-2 ring-primary/50" : done ? "border-primary/50" : "border-border-strong",
                done ? "bg-primary-soft text-brand shadow-[0_0_12px_-4px_var(--primary)]" : "bg-surface-2/60 text-muted hover:bg-surface-3/70 hover:text-ink",
              )}
            >
              {position + 1}
              {marked ? <Flag className="absolute -right-1 -top-1 h-3 w-3 fill-warning text-warning" aria-hidden /> : null}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function Legend({ t }: { t: TFunction }) {
  const item = "flex items-center gap-2 text-xs text-muted";
  return (
    <ul className="space-y-1.5 border-t border-border px-4 py-3">
      <li className={item}>
        <span className="h-3.5 w-3.5 rounded-sm border border-primary/50 bg-primary-soft" aria-hidden />
        {t("qz.exam.answered")}
      </li>
      <li className={item}>
        <span className="h-3.5 w-3.5 rounded-sm border border-border-strong bg-surface-2" aria-hidden />
        {t("qz.exam.notAnswered")}
      </li>
      <li className={item}>
        <Flag className="h-3.5 w-3.5 fill-warning text-warning" aria-hidden />
        {t("qz.exam.flagged")}
      </li>
      <li className={item}>
        <span className="h-3.5 w-3.5 rounded-sm border border-primary ring-2 ring-primary/50" aria-hidden />
        {t("qz.exam.current")}
      </li>
    </ul>
  );
}

function AnswerControl({
  question,
  value,
  disabled,
  onChange,
  t,
}: {
  question: ExamQuestion;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  t: TFunction;
}) {
  const choice = (selected: boolean) =>
    clsx(
      "flex cursor-pointer items-start gap-3 rounded-2xl border-2 px-4 py-3.5 text-sm transition-all focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-primary",
      selected ? "border-primary bg-primary-soft shadow-glow" : "border-border bg-surface-2/50 hover:border-border-strong hover:bg-surface-3/50",
      disabled && "cursor-not-allowed opacity-70",
    );

  if (question.qtype === "mcq") {
    return (
      <fieldset className="space-y-2" disabled={disabled}>
        <legend className="sr-only">{plain(question.prompt)}</legend>
        {(question.options ?? []).map((option, optionIndex) => {
          const selected = value === String(optionIndex);
          return (
            <label key={optionIndex} className={choice(selected)}>
              <input
                type="radio"
                name={`q-${question.id}`}
                checked={selected}
                onChange={() => onChange(String(optionIndex))}
                className="sr-only"
              />
              <span
                aria-hidden
                className={clsx(
                  "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold",
                  selected ? "border-primary bg-primary text-on-primary" : "border-border-strong text-muted",
                )}
              >
                {optionLetter(optionIndex)}
              </span>
              <QuizMarkdown text={option} className={clsx("min-w-0 flex-1", INLINE_MD)} />
            </label>
          );
        })}
        {value !== "" && !disabled ? (
          <button type="button" onClick={() => onChange("")} className="text-xs text-muted underline-offset-2 hover:text-ink hover:underline">
            {t("qz.exam.clear")}
          </button>
        ) : null}
      </fieldset>
    );
  }

  if (question.qtype === "true_false") {
    return (
      <fieldset className="grid grid-cols-2 gap-2" disabled={disabled}>
        <legend className="sr-only">{plain(question.prompt)}</legend>
        {(["true", "false"] as const).map((option) => {
          const selected = value === option;
          return (
            <label key={option} className={clsx(choice(selected), "items-center justify-center py-3 font-medium")}>
              <input type="radio" name={`q-${question.id}`} checked={selected} onChange={() => onChange(option)} className="sr-only" />
              {t(`quiz.take.${option}`)}
            </label>
          );
        })}
        {value !== "" && !disabled ? (
          <button type="button" onClick={() => onChange("")} className="col-span-2 justify-self-start text-xs text-muted underline-offset-2 hover:text-ink hover:underline">
            {t("qz.exam.clear")}
          </button>
        ) : null}
      </fieldset>
    );
  }

  return (
    <div>
      <label htmlFor={`short-${question.id}`} className="sr-only">
        {t("quiz.take.answerHere")}
      </label>
      <Textarea
        id={`short-${question.id}`}
        value={value}
        maxLength={MAX_RESPONSE_CHARS}
        rows={7}
        disabled={disabled}
        placeholder={t("quiz.take.answerHere")}
        onChange={(event) => onChange(event.target.value)}
        className="text-[15px]"
      />
      <p className="mt-1 flex justify-between gap-3 text-xs text-muted">
        <span>{t("quiz.take.shortHint")}</span>
        <span className="tabular shrink-0">
          {value.length} / {MAX_RESPONSE_CHARS}
        </span>
      </p>
    </div>
  );
}

function ReviewDialog({
  open,
  onClose,
  questions,
  answers,
  flags,
  remaining,
  busy,
  error,
  unanswered,
  onJump,
  onSubmit,
  t,
}: {
  open: boolean;
  onClose: () => void;
  questions: ExamQuestion[];
  answers: Record<string, string>;
  flags: string[];
  remaining: number | null;
  busy: boolean;
  error: string | null;
  unanswered: number;
  onJump: (position: number) => void;
  onSubmit: () => void;
  t: TFunction;
}) {
  const missing = useMemo(() => questions.filter((q) => !isAnswered(answers, q.id)), [questions, answers]);
  const marked = useMemo(() => questions.filter((q) => flags.includes(q.id)), [questions, flags]);

  const list = (items: ExamQuestion[]) => (
    <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border">
      {items.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            onClick={() => onJump(item.position - 1)}
            className="flex w-full items-baseline gap-3 px-3 py-2 text-left text-[13px] hover:bg-surface-3/50"
          >
            <span className="tabular w-6 shrink-0 text-muted">{item.position}</span>
            <span className="min-w-0 flex-1 truncate">{plain(item.prompt)}</span>
            <span className="shrink-0 text-xs text-brand">{t("qz.exam.goTo")}</span>
          </button>
        </li>
      ))}
    </ul>
  );

  return (
    <Dialog open={open} onClose={busy ? () => {} : onClose} title={t("qz.exam.reviewTitle")} wide>
      <p className="tabular text-[13px] text-muted">
        {t("quiz.take.progress", { done: questions.length - unanswered, total: questions.length })}
        {" · "}
        {t("qz.exam.unansweredCount", { count: unanswered })}
        {" · "}
        {t("qz.exam.flaggedCount", { count: marked.length })}
        {remaining !== null ? ` · ${t("qz.exam.timeLeft", { time: formatClock(remaining) })}` : ""}
      </p>

      <div className="mt-4 space-y-4">
        {missing.length > 0 ? (
          <section>
            <h3 className="mb-1.5 text-[13px] font-semibold">{t("qz.exam.listUnanswered")}</h3>
            {list(missing)}
          </section>
        ) : null}
        {marked.length > 0 ? (
          <section>
            <h3 className="mb-1.5 text-[13px] font-semibold">{t("qz.exam.listFlagged")}</h3>
            {list(marked)}
          </section>
        ) : null}
        {missing.length === 0 && marked.length === 0 ? <p className="text-sm">{t("qz.exam.allDone")}</p> : null}
      </div>

      <p className="mt-4 text-xs text-muted">{t("qz.exam.finalNote")}</p>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          {t("quiz.take.keepGoing")}
        </Button>
        <Button loading={busy} onClick={onSubmit}>
          {unanswered > 0 ? t("qz.exam.submitWith", { count: unanswered }) : t("quiz.take.finish")}
        </Button>
      </div>
    </Dialog>
  );
}
