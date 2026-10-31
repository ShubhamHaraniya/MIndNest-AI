"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { PageSkeleton } from "@/components/kit/skeleton";
import { ExamView } from "@/components/quizzes/exam";
import { Results } from "@/components/quizzes/results";
import { Alert } from "@/components/ui";
import { useT } from "@/i18n/client";
import { ApiError, api } from "@/lib/api";
import { quizError, type ExamSession } from "@/lib/quiz";
import type { Attempt } from "@/lib/types";

const POLL_MS = 2000;

/** One attempt: the exam while it is open, the analysed result once it is finished. */
export function AttemptScreen({ attemptId }: { attemptId: string }) {
  const t = useT();
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [session, setSession] = useState<ExamSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      const loaded = await api<Attempt>(`/attempts/${attemptId}`);
      setAttempt(loaded);
      if (loaded.status === "in_progress") setSession(await api<ExamSession>(`/attempts/${attemptId}/session`));
      else setSession(null);
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) setMissing(true);
      else setError(quizError(caught, t));
    }
  }, [attemptId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const grading = attempt?.status === "grading";
  useEffect(() => {
    if (!grading) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [grading, load]);

  const back = (
    <Link href="/quizzes" className="mb-3 inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
      <ChevronLeft className="h-4 w-4" aria-hidden />
      {t("qr.back")}
    </Link>
  );

  if (missing) {
    return (
      <>
        {back}
        <Alert>{t("errors.not_found")}</Alert>
      </>
    );
  }
  if (!attempt || (attempt.status === "in_progress" && !session)) {
    return (
      <>
        {back}
        {error ? <Alert>{error}</Alert> : <PageSkeleton label={t("common.loading")} />}
      </>
    );
  }
  if (attempt.status === "in_progress" && session) {
    return <ExamView key={attempt.id} session={session} onSubmitted={setAttempt} onReload={() => void load()} />;
  }
  return (
    <>
      {back}
      <Results attempt={attempt} />
    </>
  );
}
