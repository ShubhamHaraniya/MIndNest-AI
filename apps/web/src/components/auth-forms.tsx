"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Alert, Button, Field } from "@/components/ui";
import { setLocaleCookie } from "@/components/locale-switcher";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { User } from "@/lib/types";

const linkClass = "font-medium text-primary hover:underline";

function useSubmit() {
  const t = useT();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
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
  return { error, busy, run };
}

export function LoginForm({ next }: { next: string }) {
  const t = useT();
  const router = useRouter();
  const { error, busy, run } = useSubmit();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      const user = await api<User>("/auth/login", { method: "POST", body: { email, password } });
      setLocaleCookie(user.ui_language);
      router.replace(user.onboarding_completed ? next : "/onboarding");
      router.refresh();
    });
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {error ? <Alert>{error}</Alert> : null}
      <Field label={t("auth.email")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Field label={t("auth.password")} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      <div className="text-right text-sm">
        <Link href="/forgot-password" className={linkClass}>
          {t("auth.forgotLink")}
        </Link>
      </div>
      <Button type="submit" loading={busy} className="w-full">
        {t("auth.loginSubmit")}
      </Button>
      <p className="text-center text-sm text-muted">
        {t("auth.noAccount")}{" "}
        <Link href="/signup" className={linkClass}>
          {t("auth.createAccountLink")}
        </Link>
      </p>
    </form>
  );
}

/** A four-step strength hint under the password. It only guides the student; the rules that
 *  matter (the minimum length) are enforced on submit and by the server. */
function PasswordMeter({ password }: { password: string }) {
  const t = useT();
  if (!password) return null;
  const score =
    (password.length >= 10 ? 1 : 0) +
    (/\d/.test(password) ? 1 : 0) +
    (/[a-z]/.test(password) && /[A-Z]/.test(password) ? 1 : 0) +
    (/[^A-Za-z0-9]/.test(password) || password.length >= 16 ? 1 : 0);
  const level = password.length < 10 ? 0 : Math.max(score, 1);
  const labels = [t("auth.strengthShort"), t("auth.strengthWeak"), t("auth.strengthFair"), t("auth.strengthGood"), t("auth.strengthStrong")];
  const colours = ["bg-danger", "bg-danger", "bg-warning", "bg-info", "bg-success"];
  return (
    <div className="-mt-2" aria-live="polite">
      <div className="flex gap-1.5" aria-hidden>
        {[1, 2, 3, 4].map((step) => (
          <span key={step} className={`h-1.5 flex-1 rounded-full transition-colors ${level >= step ? colours[level] : "bg-surface-3"}`} />
        ))}
      </div>
      <p className="mt-1.5 text-xs text-muted">
        {t("auth.strengthLabel")}: <span className="font-medium text-ink">{labels[level]}</span>
      </p>
    </div>
  );
}

export function SignupForm() {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();
  const { error, busy, run } = useSubmit();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    setLocalError(null);
    if (password.length < 10) {
      setLocalError(t("auth.passwordHint"));
      return;
    }
    void run(async () => {
      await api<User>("/auth/signup", {
        method: "POST",
        body: { email, password, display_name: name, ui_language: locale },
      });
      router.replace("/onboarding");
      router.refresh();
    });
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {error ? <Alert>{error}</Alert> : null}
      <Field label={t("auth.name")} autoComplete="name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
      <Field label={t("auth.email")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Field
        label={t("auth.password")}
        type="password"
        autoComplete="new-password"
        required
        hint={t("auth.passwordHint")}
        error={localError}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <PasswordMeter password={password} />
      <Button type="submit" loading={busy} className="w-full">
        {t("auth.signupSubmit")}
      </Button>
      <p className="text-center text-sm text-muted">
        {t("auth.haveAccount")}{" "}
        <Link href="/login" className={linkClass}>
          {t("auth.signInLink")}
        </Link>
      </p>
    </form>
  );
}

export function ForgotPasswordForm() {
  const t = useT();
  const { error, busy, run } = useSubmit();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      await api("/auth/forgot-password", { method: "POST", body: { email } });
      setSent(true);
    });
  }

  if (sent) {
    return (
      <div className="space-y-5">
        <Alert tone="success">{t("auth.forgotSent")}</Alert>
        <Link href="/login" className={linkClass}>
          {t("auth.backToSignIn")}
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {error ? <Alert>{error}</Alert> : null}
      <Field label={t("auth.email")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Button type="submit" loading={busy} className="w-full">
        {t("auth.forgotSubmit")}
      </Button>
      <p className="text-center text-sm">
        <Link href="/login" className={linkClass}>
          {t("auth.backToSignIn")}
        </Link>
      </p>
    </form>
  );
}

export function ResetPasswordForm({ token }: { token: string | null }) {
  const t = useT();
  const { error, busy, run } = useSubmit();
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  if (!token) {
    return (
      <div className="space-y-5">
        <Alert>{t("auth.resetMissingToken")}</Alert>
        <Link href="/forgot-password" className={linkClass}>
          {t("auth.forgotLink")}
        </Link>
      </div>
    );
  }

  if (done) {
    return (
      <div className="space-y-5">
        <Alert tone="success">{t("auth.resetDone")}</Alert>
        <Link href="/login" className={linkClass}>
          {t("auth.loginSubmit")}
        </Link>
      </div>
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setLocalError(null);
    if (password.length < 10) {
      setLocalError(t("auth.passwordHint"));
      return;
    }
    void run(async () => {
      await api("/auth/reset-password", { method: "POST", body: { token, new_password: password } });
      setDone(true);
    });
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {error ? <Alert>{error}</Alert> : null}
      <Field
        label={t("auth.newPassword")}
        type="password"
        autoComplete="new-password"
        required
        hint={t("auth.passwordHint")}
        error={localError}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <Button type="submit" loading={busy} className="w-full">
        {t("auth.resetSubmit")}
      </Button>
    </form>
  );
}

export function VerifyEmail({ token }: { token: string | null }) {
  const t = useT();
  const [state, setState] = useState<"working" | "done" | "failed">(token ? "working" : "failed");
  const started = useRef(false);

  useEffect(() => {
    // The token works once, so guard against React Strict Mode running this effect twice.
    if (!token || started.current) return;
    started.current = true;
    api("/auth/verify-email", { method: "POST", body: { token } })
      .then(() => setState("done"))
      .catch(() => setState("failed"));
  }, [token]);

  if (state === "working") return <Alert tone="info">{t("auth.verifyWorking")}</Alert>;
  if (state === "done") {
    return (
      <div className="space-y-5">
        <Alert tone="success">{t("auth.verifyDone")}</Alert>
        <Link href="/dashboard" className={linkClass}>
          {t("auth.verifyContinue")}
        </Link>
      </div>
    );
  }
  return (
    <div className="space-y-5">
      <Alert>{token ? t("auth.verifyFailed") : t("auth.verifyMissingToken")}</Alert>
      <Link href="/dashboard" className={linkClass}>
        {t("auth.verifyContinue")}
      </Link>
    </div>
  );
}
