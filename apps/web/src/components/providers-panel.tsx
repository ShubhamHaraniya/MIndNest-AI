"use client";

import { CheckCircle2, ExternalLink, KeyRound } from "lucide-react";
import { useEffect, useState } from "react";

import { Dialog } from "@/components/dialog";
import { Alert, Button, Field } from "@/components/ui";
import { useT } from "@/i18n/client";
import { ApiError, api } from "@/lib/api";
import { errorMessage, llmErrorText } from "@/lib/errors";
import type { Provider } from "@/lib/types";

export function ProvidersPanel() {
  const t = useT();
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Provider[]>("/settings/providers")
      .then(setProviders)
      .catch((caught: unknown) => setError(errorMessage(caught, t)));
  }, [t]);

  function replace(updated: Provider) {
    setProviders((current) => (current ?? []).map((p) => (p.id === updated.id ? updated : p)));
  }

  return (
    <section aria-labelledby="providers-title">
      <h2 id="providers-title" className="text-lg font-semibold">
        {t("settings.providers.title")}
      </h2>
      <p className="mt-1 max-w-2xl text-sm text-muted">{t("settings.providers.intro")}</p>

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      {providers === null ? (
        error ? null : <p className="py-8 text-muted">{t("common.loading")}</p>
      ) : (
        <ul className="mt-5 grid gap-4 lg:grid-cols-2">
          {providers.map((provider) => (
            <li key={provider.id}>
              <ProviderCard provider={provider} onChange={replace} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ProviderCard({ provider, onChange }: { provider: Provider; onChange: (updated: Provider) => void }) {
  const t = useT();
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(provider.model ?? "");
  const [busy, setBusy] = useState<"save" | "test" | "remove" | "models" | null>(null);
  const [liveModels, setLiveModels] = useState<string[] | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);

  const canSave = provider.configured ? apiKey.trim().length > 0 || model !== (provider.model ?? "") : apiKey.trim().length >= 8;

  async function save() {
    setBusy("save");
    setMessage(null);
    try {
      const updated = await api<Provider>(`/settings/providers/${provider.id}`, {
        method: "PUT",
        body: { api_key: apiKey.trim() || undefined, model: model.trim() || null },
      });
      onChange(updated);
      setApiKey("");
      setModel(updated.model ?? "");
      setMessage({ tone: "success", text: t("settings.providers.saved") });
    } catch (caught) {
      setMessage({ tone: "error", text: errorMessage(caught, t) });
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setMessage(null);
    try {
      await api(`/settings/providers/${provider.id}/test`, { method: "POST" });
      setMessage({ tone: "success", text: t("settings.providers.testOk") });
    } catch (caught) {
      const text =
        caught instanceof ApiError && caught.code.startsWith("llm_")
          ? llmErrorText(caught.code.slice(4), t)
          : errorMessage(caught, t);
      setMessage({ tone: "error", text });
    } finally {
      setBusy(null);
    }
  }

  async function loadModels() {
    setBusy("models");
    setMessage(null);
    try {
      const result = await api<{ models: string[] }>(`/settings/providers/${provider.id}/models`);
      setLiveModels(result.models);
      setMessage({ tone: "success", text: t("settings.providers.modelsLoaded", { count: result.models.length }) });
    } catch (caught) {
      const text =
        caught instanceof ApiError && caught.code.startsWith("llm_")
          ? llmErrorText(caught.code.slice(4), t)
          : errorMessage(caught, t);
      setMessage({ tone: "error", text });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setConfirmRemove(false);
    setBusy("remove");
    setMessage(null);
    try {
      await api(`/settings/providers/${provider.id}`, { method: "DELETE" });
      onChange({ ...provider, configured: false, key_hint: null, model: null });
      setModel("");
      setApiKey("");
    } catch (caught) {
      setMessage({ tone: "error", text: errorMessage(caught, t) });
    } finally {
      setBusy(null);
    }
  }

  const listId = `models-${provider.id}`;

  return (
    <div className="rounded-card border border-border bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">{provider.label}</h3>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
            {provider.configured ? (
              <>
                <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-hidden />
                {t("settings.providers.configured", { hint: provider.key_hint ?? "" })}
              </>
            ) : (
              <>
                <KeyRound className="h-3.5 w-3.5" aria-hidden />
                {t("settings.providers.notConfigured")}
              </>
            )}
          </p>
        </div>
        <a
          href={provider.key_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex shrink-0 items-center gap-1 text-xs text-primary hover:underline"
        >
          {t("settings.providers.getKey")}
          <ExternalLink className="h-3 w-3" aria-hidden />
        </a>
      </div>

      <div className="mt-4 space-y-3">
        <Field
          label={provider.configured ? t("settings.providers.apiKeyReplace") : t("settings.providers.apiKey")}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
        />
        <Field
          label={t("settings.providers.model")}
          hint={t("settings.providers.modelHint", { model: provider.default_model })}
          list={listId}
          autoComplete="off"
          spellCheck={false}
          value={model}
          onChange={(event) => setModel(event.target.value)}
        />
        <datalist id={listId}>
          {(liveModels ?? provider.models).map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
      </div>

      {message ? (
        <div className="mt-3">
          <Alert tone={message.tone}>{message.text}</Alert>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button onClick={() => void save()} loading={busy === "save"} disabled={!canSave || busy !== null}>
          {t("settings.providers.save")}
        </Button>
        {provider.configured ? (
          <>
            <Button variant="secondary" onClick={() => void test()} loading={busy === "test"} disabled={busy !== null}>
              {busy === "test" ? t("settings.providers.testing") : t("settings.providers.test")}
            </Button>
            <Button variant="secondary" onClick={() => void loadModels()} loading={busy === "models"} disabled={busy !== null}>
              {t("settings.providers.loadModels")}
            </Button>
            <Button variant="ghost" onClick={() => setConfirmRemove(true)} disabled={busy !== null}>
              {t("settings.providers.remove")}
            </Button>
          </>
        ) : null}
      </div>

      <Dialog open={confirmRemove} onClose={() => setConfirmRemove(false)} title={t("settings.providers.remove")}>
        <p className="text-sm text-muted">{t("settings.providers.removeConfirm", { provider: provider.label })}</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmRemove(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant="danger" onClick={() => void remove()}>
            {t("common.delete")}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
