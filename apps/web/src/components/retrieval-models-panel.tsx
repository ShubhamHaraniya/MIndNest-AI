"use client";

import { Cpu, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CodeBlock } from "@/components/code-block";
import { Badge, Button, Facts, Panel, Skeleton } from "@/components/kit";
import { Alert } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatTime } from "@/lib/format";
import type { ModelPart, ModelsStatus } from "@/lib/types";

const START_COMMAND = "uvicorn mindnest_models.main:app --port 8100";

/** Settings > Local retrieval models. Shows what the model service on this laptop reports; when it
 *  cannot be reached it says so and shows how to start it, never made-up values. */
export function RetrievalModelsPanel() {
  const t = useT();
  const locale = useLocale();
  const [status, setStatus] = useState<ModelsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setStatus(await api<ModelsStatus>("/settings/models"));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const unknown = t("models.unknown");
  const yesNo = (value: boolean | null, yes: string, no: string) => (value === null ? unknown : value ? yes : no);

  return (
    <section aria-labelledby="models-title" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h2 id="models-title" className="text-lg font-semibold">
            {t("models.title")}
          </h2>
          <p className="mt-1 text-sm text-muted">{t("models.intro")}</p>
        </div>
        <Button variant="secondary" onClick={() => void load()} loading={busy}>
          {busy ? null : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
          {t("models.check")}
        </Button>
      </div>

      <Alert tone="info">{t("models.noLocalLlm")}</Alert>

      {error ? <Alert>{error}</Alert> : null}

      {status === null ? (
        error ? null : (
          <div className="space-y-2" aria-busy="true" aria-label={t("common.loading")}>
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        )
      ) : (
        <>
          {status.reachable ? (
            <p className="flex items-center gap-2 text-sm">
              <Badge tone="success">{t("models.running")}</Badge>
              <span className="text-muted">
                {t("models.answered", { service: status.service, ms: status.latency_ms ?? 0 })}
              </span>
            </p>
          ) : (
            <div className="space-y-2">
              <Alert>
                <p className="font-medium">{t("models.down")}</p>
                <p className="mt-0.5 text-xs">{t(`models.problem.${status.problem ?? "unreachable"}` as MessageKey)}</p>
              </Alert>
              <p className="text-xs text-muted">{t("models.start", { service: status.service })}</p>
              <CodeBlock language="powershell" code={START_COMMAND} />
              <p className="text-xs text-muted">{t("models.degraded")}</p>
            </div>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <ModelCard title={t("models.embedding")} body={t("models.embedding.body")} part={status.embedding} />
            <ModelCard title={t("models.reranker")} body={t("models.reranker.body")} part={status.reranker} />
          </div>

          <Panel title={t("models.config")} bodyClassName="p-3.5">
            <Facts
              className="sm:grid-cols-2 lg:grid-cols-3"
              items={[
                { label: t("models.f.service"), value: status.service },
                { label: t("models.f.backend"), value: status.backend ?? unknown },
                {
                  label: t("models.f.dim"),
                  value:
                    status.dim === null
                      ? unknown
                      : `${status.dim}${status.dim_matches === false ? ` (${t("models.f.dimExpected", { dim: status.expected_dim })})` : ""}`,
                },
                {
                  label: t("models.f.gpu"),
                  value:
                    status.cuda_available === null
                      ? unknown
                      : status.cuda_available
                        ? (status.gpu_name ?? t("models.f.gpuYes"))
                        : t("models.f.gpuNo"),
                },
                { label: t("models.f.precision"), value: status.precision ?? unknown },
                { label: t("models.f.seq"), value: status.max_seq_length === null ? unknown : String(status.max_seq_length) },
                {
                  label: t("models.f.batch"),
                  value:
                    status.embed_batch_size === null || status.rerank_batch_size === null
                      ? unknown
                      : `${status.embed_batch_size} / ${status.rerank_batch_size}`,
                },
                { label: t("models.f.latency"), value: status.latency_ms === null ? unknown : `${status.latency_ms} ms` },
                { label: t("models.f.checked"), value: formatTime(status.checked_at, locale) },
              ]}
            />
            {status.dim_matches === false ? (
              <div className="mt-3">
                <Alert>{t("models.dimWarning", { dim: status.dim ?? 0, expected: status.expected_dim })}</Alert>
              </div>
            ) : null}
            <p className="mt-3 text-xs text-muted">
              {yesNo(status.cuda_available, t("models.gpuHint.yes"), t("models.gpuHint.no"))}
            </p>
          </Panel>

          <Panel title={t("models.usage")} bodyClassName="space-y-2 p-3.5 text-[13px]">
            <p className="text-muted">{t("models.usage.intro")}</p>
            <ul className="space-y-1.5">
              {status.modes.map((mode) => (
                <li key={mode} className="flex gap-2">
                  <Badge tone={mode === "advanced" ? "brand" : "neutral"}>{t(`models.mode.${mode}` as MessageKey)}</Badge>
                  <span className="text-muted">{t(`models.mode.${mode}.body` as MessageKey)}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted">{t("models.usage.constants", { chars: status.rerank_chars, k: status.rrf_k })}</p>
          </Panel>
        </>
      )}
    </section>
  );
}

function ModelCard({ title, body, part }: { title: string; body: string; part: ModelPart | null }) {
  const t = useT();
  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-primary-soft text-brand">
          <Cpu className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          <p className="mt-0.5 text-xs text-muted">{body}</p>
        </div>
      </div>
      {part ? (
        <dl className="mt-3 space-y-1.5 text-[13px]">
          <div className="flex justify-between gap-3">
            <dt className="text-muted">{t("models.f.model")}</dt>
            <dd className="min-w-0 truncate font-mono text-xs" title={part.name}>
              {part.name}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">{t("models.f.state")}</dt>
            <dd>
              {part.loaded === null ? (
                t("models.unknown")
              ) : part.loaded ? (
                <Badge tone="success">{t("models.loaded")}</Badge>
              ) : (
                <Badge>{t("models.notLoaded")}</Badge>
              )}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">{t("models.f.device")}</dt>
            <dd>{part.device ?? t("models.unknown")}</dd>
          </div>
        </dl>
      ) : (
        <p className="mt-3 text-xs text-muted">{t("models.unavailable")}</p>
      )}
    </div>
  );
}
