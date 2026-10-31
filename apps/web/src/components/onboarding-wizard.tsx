"use client";

import clsx from "clsx";
import { Check } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";

import { setLocaleCookie } from "@/components/locale-switcher";
import { InstitutionField } from "@/components/library/institution-field";
import { Alert, Button, Field } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import { LOCALES, LOCALE_NAMES } from "@/i18n/config";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Language, Subject, User } from "@/lib/types";

const TOTAL = 5;
const selectClass =
  "h-11 w-full rounded-control border border-border bg-surface-2/60 px-3.5 text-sm text-ink hover:border-border-strong focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25 ";

function timezoneOptions(current: string): string[] {
  let zones: string[] = [];
  try {
    zones = (Intl as unknown as { supportedValuesOf(key: string): string[] }).supportedValuesOf("timeZone");
  } catch {
    zones = [];
  }
  if (!zones.includes("UTC")) zones = ["UTC", ...zones];
  if (!zones.includes(current)) zones = [current, ...zones];
  return zones;
}

export function OnboardingWizard({ user }: { user: User }) {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();

  // onboarding_step counts completed steps, so resuming lands on the next unfinished one.
  const [step, setStep] = useState(Math.min(user.onboarding_step, TOTAL - 1));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const detectedZone = useMemo(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch {
      return "UTC";
    }
  }, []);
  const [name, setName] = useState(user.display_name);
  const [timezone, setTimezone] = useState(user.timezone === "UTC" ? detectedZone : user.timezone);
  const [answerLanguage, setAnswerLanguage] = useState<Language | "">(user.answer_language ?? "");
  const [institution, setInstitution] = useState(user.institution_name);
  const [subjectName, setSubjectName] = useState("");
  const [subjectCode, setSubjectCode] = useState("");
  const [addedSubject, setAddedSubject] = useState<string | null>(null);
  const zones = useMemo(() => timezoneOptions(timezone), [timezone]);

  async function guarded(action: () => Promise<void>) {
    setError(null);
    setBusy(true);
    try {
      await action();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  function saveAndAdvance(fields: Record<string, unknown>) {
    return guarded(async () => {
      await api<User>("/me", { method: "PATCH", body: { ...fields, onboarding_step: step + 1 } });
      setStep(step + 1);
    });
  }

  function submitProfile(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    void saveAndAdvance({ display_name: name, timezone, institution_name: institution.trim() });
  }

  function submitLanguages(event: FormEvent) {
    event.preventDefault();
    void saveAndAdvance({ answer_language: answerLanguage === "" ? null : answerLanguage });
  }

  function submitSubject(event: FormEvent) {
    event.preventDefault();
    if (!subjectName.trim()) return;
    void guarded(async () => {
      const created = await api<Subject>("/subjects", {
        method: "POST",
        body: { name: subjectName, course_code: subjectCode || null },
      });
      setAddedSubject(created.name);
      await api<User>("/me", { method: "PATCH", body: { onboarding_step: step + 1 } });
      setStep(step + 1);
    });
  }

  function finish() {
    void guarded(async () => {
      await api<User>("/me", { method: "PATCH", body: { onboarding_step: TOTAL, onboarding_completed: true } });
      router.replace("/dashboard");
      router.refresh();
    });
  }

  async function changeUiLanguage(value: Language) {
    setLocaleCookie(value);
    await api("/me", { method: "PATCH", body: { ui_language: value } }).catch(() => {});
    router.refresh();
  }

  const STEP_TITLES = [
    t("onboarding.profileTitle"),
    t("onboarding.languagesTitle"),
    t("onboarding.subjectTitle"),
    t("onboarding.aiTitle"),
    t("onboarding.doneTitle"),
  ];
  const heading = STEP_TITLES[step];

  const fill = step / (TOTAL - 1);

  return (
    <div className="grid gap-6 md:grid-cols-[15rem_minmax(0,1fr)] md:gap-8">
      {/* Phones: a slim bar. */}
      <div className="md:hidden">
        <p className="mb-2 text-sm text-muted">{t("onboarding.progress", { current: step + 1, total: TOTAL })}</p>
        <div className="h-1.5 overflow-hidden rounded-full bg-surface-3" aria-hidden>
          <motion.span
            className="block h-full rounded-full bg-gradient-to-r from-primary to-accent"
            initial={false}
            animate={{ width: `${Math.max(fill, 0.06) * 100}%` }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          />
        </div>
      </div>

      {/* Larger screens: the five steps down a glowing rail that fills as you go. */}
      <aside className="glass hidden self-start rounded-3xl p-5 md:block">
        <p className="mb-4 text-xs font-semibold uppercase tracking-wider text-faint rtl:tracking-normal">
          {t("onboarding.progress", { current: step + 1, total: TOTAL })}
        </p>
        <ol className="relative space-y-5" aria-label={t("onboarding.progress", { current: step + 1, total: TOTAL })}>
          <span aria-hidden className="absolute bottom-3 left-[13px] top-3 w-px bg-surface-3" />
          <motion.span
            aria-hidden
            className="absolute left-[13px] top-3 w-px origin-top bg-gradient-to-b from-primary to-accent"
            style={{ bottom: "0.75rem", boxShadow: "0 0 10px var(--primary)" }}
            initial={false}
            animate={{ scaleY: fill }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          />
          {STEP_TITLES.map((title, index) => (
            <li key={title} className="relative flex items-center gap-3" aria-current={index === step ? "step" : undefined}>
              <span
                className={clsx(
                  "relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                  index < step && "bg-success text-on-primary",
                  index === step && "bg-primary text-on-primary shadow-glow",
                  index > step && "border border-border bg-surface-2 text-faint",
                )}
              >
                {index < step ? <Check className="h-4 w-4" aria-hidden /> : index + 1}
              </span>
              <span className={clsx("text-sm transition-colors", index === step ? "font-semibold text-ink" : index < step ? "text-muted" : "text-faint")}>
                {title}
              </span>
            </li>
          ))}
        </ol>
      </aside>

      <AnimatePresence mode="wait" initial={false}>
      <motion.section
        key={step}
        initial={{ opacity: 0, x: 18 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -18 }}
        transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
        className="glass-strong sheen min-w-0 rounded-3xl p-6 sm:p-8"
      >
        <h2 className="font-display text-2xl">{heading}</h2>
        {error ? (
          <div className="mt-4">
            <Alert>{error}</Alert>
          </div>
        ) : null}

        {step === 0 ? (
          <form onSubmit={submitProfile} className="mt-4 space-y-5">
            <p className="text-muted">{t("onboarding.profileBody")}</p>
            <Field label={t("auth.name")} required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
            <div>
              <label htmlFor="tz" className="mb-1.5 block text-sm font-medium">
                {t("onboarding.timezone")}
              </label>
              <select id="tz" className={selectClass} value={timezone} onChange={(e) => setTimezone(e.target.value)}>
                {zones.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone}
                  </option>
                ))}
              </select>
            </div>
            <InstitutionField value={institution} onChange={setInstitution} hint={t("inst.hintOnboarding")} />
            <div className="flex justify-end">
              <Button type="submit" loading={busy}>
                {t("common.next")}
              </Button>
            </div>
          </form>
        ) : null}

        {step === 1 ? (
          <form onSubmit={submitLanguages} className="mt-4 space-y-5">
            <p className="text-muted">{t("onboarding.languagesBody")}</p>
            <div>
              <label htmlFor="ui-lang" className="mb-1.5 block text-sm font-medium">
                {t("onboarding.uiLanguage")}
              </label>
              <select
                id="ui-lang"
                className={selectClass}
                value={locale}
                onChange={(e) => void changeUiLanguage(e.target.value as Language)}
              >
                {LOCALES.map((code) => (
                  <option key={code} value={code}>
                    {LOCALE_NAMES[code]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="answer-lang" className="mb-1.5 block text-sm font-medium">
                {t("onboarding.answerLanguage")}
              </label>
              <select
                id="answer-lang"
                className={selectClass}
                value={answerLanguage}
                onChange={(e) => setAnswerLanguage(e.target.value as Language | "")}
              >
                <option value="">{t("onboarding.answerSame")}</option>
                {LOCALES.map((code) => (
                  <option key={code} value={code}>
                    {LOCALE_NAMES[code]}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(step - 1)}>
                {t("common.back")}
              </Button>
              <Button type="submit" loading={busy}>
                {t("common.next")}
              </Button>
            </div>
          </form>
        ) : null}

        {step === 2 ? (
          <form onSubmit={submitSubject} className="mt-4 space-y-5">
            <p className="text-muted">{t("onboarding.subjectBody")}</p>
            <Field label={t("onboarding.subjectName")} maxLength={120} value={subjectName} onChange={(e) => setSubjectName(e.target.value)} />
            <Field
              label={t("onboarding.subjectCode")}
              optionalLabel={t("common.optional")}
              maxLength={40}
              value={subjectCode}
              onChange={(e) => setSubjectCode(e.target.value)}
            />
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(step - 1)}>
                {t("common.back")}
              </Button>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => void saveAndAdvance({})} disabled={busy}>
                  {t("common.skip")}
                </Button>
                <Button type="submit" loading={busy} disabled={!subjectName.trim()}>
                  {t("subjects.new")}
                </Button>
              </div>
            </div>
          </form>
        ) : null}

        {step === 3 ? (
          <div className="mt-4 space-y-5">
            {addedSubject ? <Alert tone="success">{t("onboarding.subjectAdded", { name: addedSubject })}</Alert> : null}
            <p className="text-muted">{t("onboarding.aiBody")}</p>
            <ul className="space-y-2">
              {(["onboarding.ai1", "onboarding.ai2", "onboarding.ai3"] as const).map((key) => (
                <li key={key} className="flex items-start gap-2 text-sm">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
                  {t(key)}
                </li>
              ))}
            </ul>
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(step - 1)}>
                {t("common.back")}
              </Button>
              <Button onClick={() => void saveAndAdvance({})} loading={busy}>
                {t("common.next")}
              </Button>
            </div>
          </div>
        ) : null}

        {step === 4 ? (
          <div className="mt-4 space-y-5">
            <p className="text-muted">{t("onboarding.doneBody")}</p>
            <div className="flex justify-end">
              <Button onClick={finish} loading={busy}>
                {t("onboarding.finish")}
              </Button>
            </div>
          </div>
        ) : null}
      </motion.section>
      </AnimatePresence>
    </div>
  );
}
