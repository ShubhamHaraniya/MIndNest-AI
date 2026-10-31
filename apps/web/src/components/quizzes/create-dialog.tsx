"use client";

import { useEffect, useId, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { FormRow, Input, Segmented, Select } from "@/components/kit/controls";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import {
  DIFFICULTIES,
  MAX_QUESTIONS,
  MIN_QUESTIONS,
  QUESTION_TYPES,
  QUIZ_LANGUAGES,
  TIME_LIMITS,
  beginAttempt,
  quizError,
  typeLabelKey,
} from "@/lib/quiz";
import type { Language, Material, Quiz, QuizType, Subject } from "@/lib/types";

type Basis = "notes" | "general" | "revision";

/** Make a quiz from the course's materials (or one document), from general knowledge about a
 *  topic, or start a revision round from the cards that are due. */
export function CreateQuizDialog({
  open,
  onClose,
  subjects,
  defaultCourse,
  dueBySubject,
  onCreated,
  onRevision,
}: {
  open: boolean;
  onClose: () => void;
  subjects: Subject[];
  defaultCourse: string | null;
  /** Revision cards due now, per course id ("" = every course). */
  dueBySubject: Record<string, number>;
  onCreated: (quiz: Quiz) => void;
  onRevision: (attemptId: string) => void;
}) {
  const t = useT();
  const locale = useLocale();
  const uid = useId();
  const [basis, setBasis] = useState<Basis>("notes");
  const [courseId, setCourseId] = useState(defaultCourse ?? "");
  const [documentId, setDocumentId] = useState("");
  const [documents, setDocuments] = useState<Material[]>([]);
  const [topic, setTopic] = useState("");
  const [title, setTitle] = useState("");
  const [count, setCount] = useState(10);
  const [types, setTypes] = useState<QuizType[]>([...QUESTION_TYPES]);
  const [difficulty, setDifficulty] = useState<(typeof DIFFICULTIES)[number]>("medium");
  const [language, setLanguage] = useState<Language>(locale);
  const [limit, setLimit] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // A course is always chosen for a quiz; revision may span every course.
  useEffect(() => {
    if (!open || basis === "revision") return;
    setCourseId((current) => current || defaultCourse || subjects[0]?.id || "");
  }, [open, basis, defaultCourse, subjects]);

  const subject = subjects.find((candidate) => candidate.id === courseId) ?? null;

  useEffect(() => {
    setDocumentId("");
    setDocuments([]);
    if (!open || basis !== "notes" || !courseId) return;
    let live = true;
    api<Material[]>(`/subjects/${courseId}/materials`)
      .then((items) => live && setDocuments(items.filter((item) => item.status === "ready")))
      .catch(() => live && setDocuments([]));
    return () => {
      live = false;
    };
  }, [open, basis, courseId]);

  function toggle(type: QuizType) {
    setTypes((current) => (current.includes(type) ? current.filter((candidate) => candidate !== type) : [...current, type]));
  }

  const noMaterials = basis === "notes" && subject !== null && subject.material_count === 0;
  const revisionDue = dueBySubject[courseId] ?? 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    setBusy(true);
    try {
      if (basis === "revision") {
        const quiz = await api<Quiz>("/revision/start", {
          method: "POST",
          body: { count: Math.min(count, MAX_QUESTIONS), subject_id: courseId || null },
        });
        onRevision(await beginAttempt(quiz.id));
        return;
      }
      if (!courseId) return;
      if (types.length === 0) {
        setMessage(t("quiz.create.noTypes"));
        return;
      }
      if (basis === "general" && !topic.trim()) {
        setMessage(t("qz.create.topicNeeded"));
        return;
      }
      const quiz = await api<Quiz>("/quizzes", {
        method: "POST",
        body: {
          subject_id: courseId,
          title: title.trim() || null,
          count,
          types,
          difficulty,
          language,
          time_limit_minutes: limit > 0 ? limit : null,
          basis: basis === "general" ? "general" : "notes",
          topic: basis === "general" ? topic.trim() : null,
          material_id: basis === "notes" && documentId ? documentId : null,
        },
      });
      onCreated(quiz);
    } catch (caught) {
      setMessage(quizError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  const revising = basis === "revision";
  const cannot = revising ? revisionDue === 0 : noMaterials || subjects.length === 0;

  return (
    <Dialog open={open} onClose={onClose} title={t("quiz.create.title")} wide>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <div>
          <p className="mb-1 text-[13px] font-medium" id={`${uid}-basis`}>
            {t("qz.create.basis")}
          </p>
          <Segmented<Basis>
            label={t("qz.create.basis")}
            value={basis}
            onChange={setBasis}
            options={[
              { value: "notes", label: t("qz.create.basisNotes") },
              { value: "general", label: t("qz.create.basisGeneral") },
              { value: "revision", label: t("qz.create.basisRevision") },
            ]}
          />
          <p className="mt-1.5 text-xs text-muted">
            {t(basis === "notes" ? "qz.create.hintNotes" : basis === "general" ? "qz.create.hintGeneral" : "qz.create.hintRevision")}
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <FormRow label={t("quiz.create.subject")} htmlFor={`${uid}-course`}>
            <Select id={`${uid}-course`} value={courseId} onChange={(event) => setCourseId(event.target.value)} className="w-full">
              {revising ? <option value="">{t("quiz.revision.allSubjects")}</option> : null}
              {subjects.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name}
                  {revising && (dueBySubject[candidate.id] ?? 0) > 0 ? ` (${dueBySubject[candidate.id]})` : ""}
                </option>
              ))}
            </Select>
          </FormRow>
          {basis === "notes" ? (
            <FormRow label={t("qz.create.scope")} htmlFor={`${uid}-doc`}>
              <Select id={`${uid}-doc`} value={documentId} onChange={(event) => setDocumentId(event.target.value)} className="w-full">
                <option value="">{t("qz.create.scopeAll")}</option>
                {documents.map((doc) => (
                  <option key={doc.id} value={doc.id}>
                    {doc.filename}
                  </option>
                ))}
              </Select>
            </FormRow>
          ) : null}
          {basis === "general" ? (
            <FormRow label={t("qz.create.topic")} htmlFor={`${uid}-topic`}>
              <Input
                id={`${uid}-topic`}
                value={topic}
                maxLength={200}
                placeholder={t("qz.create.topicPlaceholder")}
                onChange={(event) => setTopic(event.target.value)}
              />
            </FormRow>
          ) : null}
        </div>

        {noMaterials ? <p className="text-sm text-warning">{t("quiz.create.noSubjects")}</p> : null}
        {revising ? (
          <p className="text-sm">
            {revisionDue > 0 ? t("quiz.revision.due", { count: revisionDue }) : t("quiz.revision.none")}
          </p>
        ) : null}

        {!revising ? (
          <FormRow label={t("quiz.create.name")} htmlFor={`${uid}-title`}>
            <Input
              id={`${uid}-title`}
              value={title}
              maxLength={120}
              placeholder={t("common.optional")}
              onChange={(event) => setTitle(event.target.value)}
            />
          </FormRow>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <FormRow label={`${t("quiz.create.count")}: ${count}`} htmlFor={`${uid}-count`}>
            <input
              id={`${uid}-count`}
              type="range"
              min={revising ? 1 : MIN_QUESTIONS}
              max={MAX_QUESTIONS}
              value={count}
              onChange={(event) => setCount(Number(event.target.value))}
              className="h-9 w-full accent-primary"
            />
          </FormRow>
          {!revising ? (
            <FormRow label={t("qz.create.timeLimit")} htmlFor={`${uid}-limit`}>
              <Select id={`${uid}-limit`} value={limit} onChange={(event) => setLimit(Number(event.target.value))} className="w-full">
                {TIME_LIMITS.map((minutes) => (
                  <option key={minutes} value={minutes}>
                    {minutes === 0 ? t("qz.limit.none") : t("qz.min", { n: minutes })}
                  </option>
                ))}
              </Select>
            </FormRow>
          ) : null}
        </div>

        {!revising ? (
          <>
            <fieldset>
              <legend className="mb-1 text-[13px] font-medium">{t("quiz.create.types")}</legend>
              <div className="flex flex-wrap gap-x-5 gap-y-1.5">
                {QUESTION_TYPES.map((type) => (
                  <label key={type} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={types.includes(type)} onChange={() => toggle(type)} className="h-4 w-4 accent-primary" />
                    {t(typeLabelKey(type))}
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="mb-1 text-[13px] font-medium">{t("quiz.create.difficulty")}</p>
                <Segmented<(typeof DIFFICULTIES)[number]>
                  label={t("quiz.create.difficulty")}
                  value={difficulty}
                  onChange={setDifficulty}
                  options={DIFFICULTIES.map((level) => ({ value: level, label: t(`quiz.difficulty.${level}`) }))}
                />
              </div>
              <FormRow label={t("quiz.create.language")} htmlFor={`${uid}-lang`}>
                <Select id={`${uid}-lang`} value={language} onChange={(event) => setLanguage(event.target.value as Language)} className="w-full">
                  {QUIZ_LANGUAGES.map((code) => (
                    <option key={code} value={code}>
                      {t(`eval.lang.${code}`)}
                    </option>
                  ))}
                </Select>
              </FormRow>
            </div>
            <p className="text-xs text-muted">{t("quiz.create.hint")}</p>
          </>
        ) : null}

        {message ? (
          <p role="alert" className="text-sm text-danger">
            {message}
          </p>
        ) : null}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={cannot}>
            {revising ? t("quiz.revision.start") : t("quiz.create.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
