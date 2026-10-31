"use client";

import { useState, type FormEvent } from "react";

import { setLocaleCookie } from "@/components/locale-switcher";
import { GcalPanel } from "@/components/gcal-panel";
import { Button, Tabs, Select, Input, FormRow, type TabItem } from "@/components/kit";
import { InstitutionField } from "@/components/library/institution-field";
import { PrivacyPanel } from "@/components/privacy-panel";
import { ProvidersPanel } from "@/components/providers-panel";
import { SecurityPanel } from "@/components/security-panel";
import { RetrievalModelsPanel } from "@/components/retrieval-models-panel";
import { Alert } from "@/components/ui";
import { useRouter } from "next/navigation";
import { useT } from "@/i18n/client";
import { LOCALES, LOCALE_NAMES } from "@/i18n/config";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Language, User } from "@/lib/types";

type Tab = "account" | "security" | "providers" | "models" | "calendar" | "privacy";

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

export function SettingsView({ user, initialTab, gcalNotice }: { user: User; initialTab?: string; gcalNotice?: string }) {
  const t = useT();
  const start: Tab = ["account", "security", "providers", "models", "calendar", "privacy"].includes(initialTab ?? "") ? (initialTab as Tab) : "account";
  const [tab, setTab] = useState<Tab>(start);

  const items: TabItem<Tab>[] = [
    { id: "account", label: t("settings.tab.account") },
    { id: "security", label: t("settings.tab.security") },
    { id: "providers", label: t("settings.tab.providers") },
    { id: "models", label: t("settings.tab.models") },
    { id: "calendar", label: t("settings.tab.calendar") },
    { id: "privacy", label: t("settings.tab.privacy") },
  ];

  function select(next: Tab) {
    setTab(next);
    // Keep the section in the address so a reload (or a link) lands on the same tab.
    window.history.replaceState(null, "", `?tab=${next}`);
  }

  return (
    <div className="max-w-4xl">
      <Tabs items={items} value={tab} onChange={select} label={t("settings.tabs")} />
      <div className="pt-5" role="tabpanel">
        {tab === "account" ? <AccountForm user={user} /> : null}
        {tab === "security" ? <SecurityPanel /> : null}
        {tab === "providers" ? <ProvidersPanel /> : null}
        {tab === "models" ? <RetrievalModelsPanel /> : null}
        {tab === "calendar" ? <GcalPanel initialNotice={gcalNotice} /> : null}
        {tab === "privacy" ? <PrivacyPanel initialMask={user.mask_personal_data} /> : null}
      </div>
    </div>
  );
}

function AccountForm({ user }: { user: User }) {
  const t = useT();
  const router = useRouter();
  const [name, setName] = useState(user.display_name);
  const [timezone, setTimezone] = useState(user.timezone);
  const [uiLanguage, setUiLanguage] = useState<Language>(user.ui_language);
  const [answerLanguage, setAnswerLanguage] = useState<Language | "">(user.answer_language ?? "");
  const [institution, setInstitution] = useState(user.institution_name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const zones = timezoneOptions(user.timezone);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await api<User>("/me", {
        method: "PATCH",
        body: {
          display_name: name.trim(),
          timezone,
          ui_language: uiLanguage,
          answer_language: answerLanguage === "" ? null : answerLanguage,
          institution_name: institution.trim(),
        },
      });
      setLocaleCookie(uiLanguage);
      setSaved(true);
      router.refresh();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="account-title" className="max-w-xl">
      <h2 id="account-title" className="text-base font-semibold">
        {t("settings.account.title")}
      </h2>
      <p className="mt-1 text-sm text-muted">{t("settings.account.intro")}</p>
      <form onSubmit={submit} className="mt-4 space-y-4">
        <FormRow label={t("settings.account.email")} htmlFor="acct-email" hint={t("settings.account.emailHint")}>
          <div className="flex items-center gap-2">
            <Input id="acct-email" value={user.email} readOnly disabled />
            <span className="shrink-0 text-xs text-muted">
              {user.email_verified ? t("settings.account.verified") : t("settings.account.unverified")}
            </span>
          </div>
        </FormRow>
        <FormRow label={t("auth.name")} htmlFor="acct-name">
          <Input id="acct-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} />
        </FormRow>
        <FormRow label={t("onboarding.timezone")} htmlFor="acct-tz">
          <Select id="acct-tz" className="w-full" value={timezone} onChange={(e) => setTimezone(e.target.value)}>
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </Select>
        </FormRow>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormRow label={t("onboarding.uiLanguage")} htmlFor="acct-ui">
            <Select id="acct-ui" className="w-full" value={uiLanguage} onChange={(e) => setUiLanguage(e.target.value as Language)}>
              {LOCALES.map((code) => (
                <option key={code} value={code}>
                  {LOCALE_NAMES[code]}
                </option>
              ))}
            </Select>
          </FormRow>
          <FormRow label={t("onboarding.answerLanguage")} htmlFor="acct-answer">
            <Select
              id="acct-answer"
              className="w-full"
              value={answerLanguage}
              onChange={(e) => setAnswerLanguage(e.target.value as Language | "")}
            >
              <option value="">{t("onboarding.answerSame")}</option>
              {LOCALES.map((code) => (
                <option key={code} value={code}>
                  {LOCALE_NAMES[code]}
                </option>
              ))}
            </Select>
          </FormRow>
        </div>
        <InstitutionField value={institution} onChange={setInstitution} id="acct-institution" />
        {error ? <Alert>{error}</Alert> : null}
        <div className="flex items-center gap-3">
          <Button type="submit" loading={busy} disabled={!name.trim()}>
            {t("common.save")}
          </Button>
          {saved ? (
            <span role="status" className="text-sm text-muted">
              {t("settings.account.saved")}
            </span>
          ) : null}
        </div>
      </form>
    </section>
  );
}
