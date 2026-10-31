"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { DraftResult, ExamSession } from "@/lib/quiz";

export type SaveState = "saved" | "saving" | "error" | "closed";
type Answers = Record<string, string>;

const SAVE_DELAY_MS = 700;
const RETRY_MS = 5000;

function pendingKey(attemptId: string): string {
  return `mindnest.quiz.pending.${attemptId}`;
}

type Pending = { answers: Answers; flags: string[] | null };

/** Work that could not be sent yet (a flaky connection, a reload before the save finished). */
function readPending(attemptId: string): Pending {
  try {
    const raw = localStorage.getItem(pendingKey(attemptId));
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Pending>;
      return { answers: parsed.answers ?? {}, flags: parsed.flags ?? null };
    }
  } catch {
    // Storage can be blocked; the server copy still exists.
  }
  return { answers: {}, flags: null };
}

function writePending(attemptId: string, pending: Pending | null): void {
  try {
    if (pending === null || (Object.keys(pending.answers).length === 0 && pending.flags === null)) {
      localStorage.removeItem(pendingKey(attemptId));
    } else {
      localStorage.setItem(pendingKey(attemptId), JSON.stringify(pending));
    }
  } catch {
    // Not fatal: the answers are still in memory and are sent as soon as the network allows.
  }
}

/** The server's clock, read once, so the countdown is right after a reload or on a wrong device
 *  clock. `remaining` is null when the attempt has no time limit. */
export function useExamClock(session: ExamSession): { elapsed: number; remaining: number | null } {
  const [skew] = useState(() => Date.parse(session.server_now) - Date.now());
  const startedMs = Date.parse(session.started_at);
  const [now, setNow] = useState(() => Date.now() + skew);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() + skew), 1000);
    return () => clearInterval(timer);
  }, [skew]);
  const elapsed = Math.max(0, (now - startedMs) / 1000);
  return { elapsed, remaining: session.limit_seconds ? Math.max(0, session.limit_seconds - elapsed) : null };
}

/** Answers and flags of one attempt, saved to the server a moment after every change. */
export function useExamDraft(session: ExamSession) {
  const attemptId = session.attempt_id;
  const [initial] = useState(() => readPending(attemptId));
  const [answers, setAnswers] = useState<Answers>(() => ({ ...session.answers, ...initial.answers }));
  const [flags, setFlags] = useState<string[]>(() => initial.flags ?? session.flags);
  const [state, setState] = useState<SaveState>("saved");
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const pending = useRef<Pending>(initial);
  const flagsRef = useRef(flags);
  const busy = useRef(false);
  const closed = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const schedule = useCallback((delay: number, run: () => void) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(run, delay);
  }, []);

  const flush = useCallback(
    async (keepalive = false): Promise<void> => {
      if (closed.current || busy.current) return;
      const sent = pending.current;
      const ids = Object.keys(sent.answers);
      if (ids.length === 0 && sent.flags === null) {
        setState("saved");
        return;
      }
      busy.current = true;
      setState("saving");
      const body = {
        answers: ids.map((id) => ({ question_id: id, response: sent.answers[id] })),
        ...(sent.flags === null ? {} : { flags: sent.flags }),
      };
      let nextDelay: number | null = null;
      try {
        if (keepalive) {
          // A page being closed cannot wait for the normal client; this request outlives it.
          const response = await fetch(`/api/v1/attempts/${attemptId}/draft`, {
            method: "PUT",
            keepalive: true,
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          if (!response.ok) {
            const envelope = (await response.json().catch(() => ({}))) as { code?: string };
            throw new ApiError(response.status, envelope.code ?? `http_${response.status}`, "Request failed.");
          }
        } else {
          await api<DraftResult>(`/attempts/${attemptId}/draft`, { method: "PUT", body });
        }
        // Keep whatever changed while the request was in flight.
        const next: Pending = { answers: {}, flags: pending.current.flags === sent.flags ? null : pending.current.flags };
        for (const id of Object.keys(pending.current.answers)) {
          if (pending.current.answers[id] !== sent.answers[id]) next.answers[id] = pending.current.answers[id];
        }
        pending.current = next;
        writePending(attemptId, next);
        setSavedAt(Date.now());
        const clean = Object.keys(next.answers).length === 0 && next.flags === null;
        setState(clean ? "saved" : "saving");
        if (!clean) nextDelay = SAVE_DELAY_MS;
      } catch (caught) {
        if (caught instanceof ApiError && (caught.code === "time_up" || caught.code === "already_submitted")) {
          closed.current = true;
          setState("closed");
        } else {
          setState("error");
          nextDelay = RETRY_MS;
        }
      } finally {
        busy.current = false;
      }
      if (nextDelay !== null) schedule(nextDelay, () => void flush());
    },
    [attemptId, schedule],
  );

  // Send what the previous visit could not, then keep saving as the student works.
  useEffect(() => {
    if (Object.keys(initial.answers).length > 0 || initial.flags !== null) void flush();
  }, [flush, initial]);

  useEffect(() => {
    const leaving = () => {
      if (document.visibilityState === "hidden") void flush(true);
    };
    document.addEventListener("visibilitychange", leaving);
    window.addEventListener("pagehide", leaving);
    return () => {
      document.removeEventListener("visibilitychange", leaving);
      window.removeEventListener("pagehide", leaving);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [flush]);

  const setAnswer = useCallback(
    (questionId: string, value: string) => {
      setAnswers((current) => ({ ...current, [questionId]: value }));
      pending.current = { ...pending.current, answers: { ...pending.current.answers, [questionId]: value } };
      writePending(attemptId, pending.current);
      setState("saving");
      schedule(SAVE_DELAY_MS, () => void flush());
    },
    [attemptId, flush, schedule],
  );

  const toggleFlag = useCallback(
    (questionId: string) => {
      const next = flagsRef.current.includes(questionId)
        ? flagsRef.current.filter((id) => id !== questionId)
        : [...flagsRef.current, questionId];
      flagsRef.current = next;
      setFlags(next);
      pending.current = { ...pending.current, flags: next };
      writePending(attemptId, pending.current);
      setState("saving");
      schedule(SAVE_DELAY_MS, () => void flush());
    },
    [attemptId, flush, schedule],
  );

  /** Called once the attempt is submitted: nothing left to save. */
  const finish = useCallback(() => {
    closed.current = true;
    pending.current = { answers: {}, flags: null };
    writePending(attemptId, null);
    if (timer.current) clearTimeout(timer.current);
  }, [attemptId]);

  return { answers, flags, state, savedAt, setAnswer, toggleFlag, flush, finish };
}
