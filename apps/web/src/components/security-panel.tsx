"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { FormRow, Input } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { Skeleton } from "@/components/kit/skeleton";
import { useToast } from "@/components/kit/toast";
import { Alert } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";

type SecuritySummary = { has_password: boolean; email_verified: boolean };
type SignIn = { id: string; device: string; created_at: string; last_seen_at: string; current: boolean };

/** Settings → Security: change password, see where you are signed in, download your data. */
export function SecurityPanel() {
  return (
    <div className="max-w-xl space-y-6">
      <PasswordSection />
      <SignInsSection />
      <ExportSection />
    </div>
  );
}

function PasswordSection() {
  const t = useT();
  const toast = useToast();
  const [summary, setSummary] = useState<SecuritySummary | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api<SecuritySummary>("/me/security")
      .then((value) => alive && setSummary(value))
      .catch(() => alive && setSummary({ has_password: true, email_verified: true }));
    return () => {
      alive = false;
    };
  }, []);

  const tooShort = next.length > 0 && next.length < 10;
  const mismatch = again.length > 0 && again !== next;
  const ready = current.length > 0 && next.length >= 10 && again === next && !busy;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await api("/me/password", { method: "POST", body: { current_password: current, new_password: next } });
      setCurrent("");
      setNext("");
      setAgain("");
      toast.success(t("sec.password.done"));
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={t("sec.password.title")} description={t("sec.password.intro")}>
      <div className="p-4">
        {summary === null ? (
          <Skeleton className="h-24 w-full" />
        ) : !summary.has_password ? (
          <p className="text-sm text-muted">{t("sec.password.googleOnly")}</p>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <FormRow label={t("sec.password.current")} htmlFor="pw-current">
              <Input
                id="pw-current"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                maxLength={128}
              />
            </FormRow>
            <FormRow
              label={t("sec.password.new")}
              htmlFor="pw-new"
              hint={t("sec.password.hint")}
              error={tooShort ? t("sec.password.tooShort") : undefined}
            >
              <Input
                id="pw-new"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                maxLength={128}
              />
            </FormRow>
            <FormRow
              label={t("sec.password.again")}
              htmlFor="pw-again"
              error={mismatch ? t("sec.password.mismatch") : undefined}
            >
              <Input
                id="pw-again"
                type="password"
                autoComplete="new-password"
                value={again}
                onChange={(e) => setAgain(e.target.value)}
                maxLength={128}
              />
            </FormRow>
            <p className="text-xs text-muted">{t("sec.password.effect")}</p>
            {error ? <Alert>{error}</Alert> : null}
            <Button type="submit" loading={busy} disabled={!ready}>
              {t("sec.password.submit")}
            </Button>
          </form>
        )}
      </div>
    </Panel>
  );
}

function SignInsSection() {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [items, setItems] = useState<SignIn[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api<{ items: SignIn[] }>("/me/sessions");
      setItems(data.items);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function signOutOthers() {
    try {
      const result = await api<{ signed_out: number }>("/me/sessions/sign-out-others", { method: "POST" });
      toast.success(t("sec.signins.done", { count: result.signed_out }));
      await load();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  const others = (items ?? []).filter((item) => !item.current).length;

  return (
    <Panel
      title={t("sec.signins.title")}
      description={t("sec.signins.intro")}
      action={
        <Button variant="secondary" size="sm" disabled={others === 0} onClick={() => setConfirming(true)}>
          {t("sec.signins.signOutOthers")}
        </Button>
      }
    >
      {failed ? (
        <div className="p-4">
          <Alert>{t("errors.generic")}</Alert>
        </div>
      ) : items === null ? (
        <div className="p-4">
          <Skeleton className="h-16 w-full" />
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {item.device === "unknown" ? t("sec.signins.unknownDevice") : item.device}
                </p>
                <p className="text-xs text-muted">
                  {t("sec.signins.lastActive", { when: formatDateTime(item.last_seen_at, locale) })}
                </p>
              </div>
              {item.current ? <Badge tone="brand">{t("sec.signins.thisDevice")}</Badge> : null}
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={confirming}
        title={t("sec.signins.confirmTitle")}
        description={t("sec.signins.confirmBody")}
        confirmLabel={t("sec.signins.signOutOthers")}
        onConfirm={signOutOthers}
        onClose={() => setConfirming(false)}
      />
    </Panel>
  );
}

function ExportSection() {
  const t = useT();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function download() {
    setBusy(true);
    try {
      const response = await fetch("/api/v1/me/export", { credentials: "same-origin" });
      if (!response.ok) {
        let code = `http_${response.status}`;
        try {
          code = ((await response.json()) as { code?: string }).code ?? code;
        } catch {
          // Not JSON; the generic message is used.
        }
        throw new ApiError(response.status, code, "Export failed.");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "mindnest-my-data.json";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={t("sec.export.title")} description={t("sec.export.intro")}>
      <div className="space-y-3 p-4">
        <p className="text-sm text-muted">{t("sec.export.contains")}</p>
        <p className="text-sm text-muted">{t("sec.export.notIncluded")}</p>
        <Button variant="secondary" loading={busy} onClick={download}>
          {t("sec.export.button")}
        </Button>
      </div>
    </Panel>
  );
}
