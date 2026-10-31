"use client";

import { CheckCircle2, Pencil, Play, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { formatDate } from "@/components/groups/model";
import { Dialog } from "@/components/dialog";
import { Badge } from "@/components/kit/badge";
import { Breadcrumbs } from "@/components/kit/breadcrumbs";
import { Button, ButtonLink } from "@/components/kit/button";
import { FormRow, SearchField, Segmented, Select, Textarea, Input } from "@/components/kit/controls";
import { Panel, Facts } from "@/components/kit/panel";
import { Skeleton } from "@/components/kit/skeleton";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useToast } from "@/components/kit/toast";
import { IconButton } from "@/components/subjects/bits";
import { Alert } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { EvalCase, EvalCheck, EvalDatasetDetail, EvidenceItem } from "@/lib/types";

function evidenceToText(items: EvidenceItem[]): string {
  return items.map((item) => (item.file ? `${item.file} | ${item.phrase}` : item.phrase)).join("\n");
}

function textToEvidence(text: string): EvidenceItem[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const bar = line.indexOf(" | ");
      return bar === -1
        ? { phrase: line }
        : { file: line.slice(0, bar).trim() || null, phrase: line.slice(bar + 3).trim() };
    });
}

type Show = "all" | "answerable" | "unanswerable" | "missing";

export function EvalDatasetView({ datasetId }: { datasetId: string }) {
  const t = useT();
  const locale = useLocale();
  const [dataset, setDataset] = useState<EvalDatasetDetail | null>(null);
  const [check, setCheck] = useState<EvalCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [editing, setEditing] = useState<EvalCase | null>(null);
  const [query, setQuery] = useState("");
  const [language, setLanguage] = useState("");
  const [show, setShow] = useState<Show>("all");

  const load = useCallback(async () => {
    try {
      setDataset(await api<EvalDatasetDetail>(`/eval/datasets/${datasetId}`));
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 404 || caught.status === 422)) setMissing(true);
      else setError(errorMessage(caught, t));
    }
  }, [datasetId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function runCheck() {
    setChecking(true);
    try {
      setCheck(await api<EvalCheck>(`/eval/datasets/${datasetId}/check`));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setChecking(false);
    }
  }

  const checkByKey = useMemo(() => new Map((check?.cases ?? []).map((entry) => [entry.key, entry])), [check]);

  const crumbs = (last: string) => (
    <Breadcrumbs
      label={t("common.breadcrumb")}
      items={[{ label: t("nav.eval"), href: "/eval" }, { label: t("eval.datasets.title"), href: "/eval" }, { label: last }]}
    />
  );

  if (missing) {
    return (
      <>
        {crumbs(t("eval.dataset.notFound"))}
        <EmptyState title={t("eval.dataset.notFound")} description={t("evx.dataset.notFoundBody")}>
          <Link href="/eval" className="text-sm font-medium text-brand hover:underline">
            {t("eval.dataset.back")}
          </Link>
        </EmptyState>
      </>
    );
  }
  if (!dataset) {
    return (
      <>
        {crumbs(t("common.loading"))}
        {error ? (
          <ErrorState compact description={error} onRetry={() => void load()} />
        ) : (
          <div className="space-y-3" aria-hidden>
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}
      </>
    );
  }

  const languages = Array.from(new Set(dataset.items.map((item) => item.language)));
  const needle = query.trim().toLocaleLowerCase();
  const shown = dataset.items.filter((item) => {
    if (language && item.language !== language) return false;
    if (show === "answerable" && !item.answerable) return false;
    if (show === "unanswerable" && item.answerable) return false;
    if (show === "missing") {
      const found = checkByKey.get(item.key);
      if (!found || found.ok || !item.answerable) return false;
    }
    if (!needle) return true;
    return `${item.key} ${item.question} ${item.reference_answer ?? ""} ${item.tags.join(" ")}`.toLocaleLowerCase().includes(needle);
  });

  return (
    <>
      {crumbs(dataset.name)}
      <header className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h1 className="font-display break-words text-2xl leading-tight">{dataset.name}</h1>
          <p className="mt-0.5 text-[13px] text-muted">{dataset.description ?? t("evx.dataset.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" loading={checking} onClick={() => void runCheck()}>
            <CheckCircle2 className="h-4 w-4" aria-hidden />
            {t("eval.dataset.check")}
          </Button>
          <ButtonLink href={`/eval?run=${dataset.id}`}>
            <Play className="h-4 w-4" aria-hidden />
            {t("evx.dataset.runIt")}
          </ButtonLink>
        </div>
      </header>

      <div className="space-y-4">
        {error ? <Alert>{error}</Alert> : null}

        <Panel id="dataset-facts" title={t("evx.runPage.about")} bodyClassName="px-3.5 py-3">
          <Facts
            className="sm:grid-cols-2 lg:grid-cols-4"
            items={[
              { label: t("evx.col.questions"), value: String(dataset.cases) },
              { label: t("evx.dataset.notIn"), value: String(dataset.unanswerable) },
              { label: t("evx.col.languages"), value: Object.entries(dataset.languages).map(([code, n]) => `${t(`eval.lang.${code as "en" | "hi" | "gu"}`)} ${n}`).join(" · ") },
              { label: t("evx.col.searches"), value: dataset.subject_name ?? t("eval.import.allSubjects") },
              { label: t("evx.col.added"), value: formatDate(dataset.created_at, locale) },
            ]}
          />
        </Panel>

        {check ? (
          <div className="space-y-1.5">
            <Alert tone={check.missing === 0 && check.chunks > 0 ? "success" : "info"}>
              {check.chunks === 0
                ? t("eval.dataset.noMaterials")
                : t("eval.dataset.checkSummary", { ok: check.ok, total: check.ok + check.missing })}
            </Alert>
            {check.materials.length > 0 ? <p className="text-xs text-muted">{t("eval.dataset.materials", { files: check.materials.join(", ") })}</p> : null}
          </div>
        ) : (
          <p className="max-w-3xl text-[13px] text-muted">{t("eval.dataset.checkIntro")}</p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <SearchField value={query} onChange={setQuery} placeholder={t("evx.dataset.search")} className="w-full sm:w-64" />
          {languages.length > 1 ? (
            <Select aria-label={t("common.language")} value={language} onChange={(event) => setLanguage(event.target.value)}>
              <option value="">{t("evx.results.allLanguages")}</option>
              {languages.map((code) => (
                <option key={code} value={code}>
                  {t(`eval.lang.${code}`)}
                </option>
              ))}
            </Select>
          ) : null}
          <Segmented
            label={t("evx.col.questions")}
            value={show}
            onChange={setShow}
            options={[
              { value: "all", label: t("eval.results.filterAll") },
              { value: "answerable", label: t("evx.dataset.answerable") },
              { value: "unanswerable", label: t("eval.dataset.notInMaterials") },
              ...(check ? [{ value: "missing" as const, label: t("evx.dataset.evidenceMissing") }] : []),
            ]}
          />
          <p className="tabular ml-auto text-xs text-muted">{t("evx.dataset.count", { shown: shown.length, total: dataset.items.length })}</p>
        </div>

        {shown.length === 0 ? (
          <NoResults title={t("evx.results.noMatch")} />
        ) : (
          <div className="rounded-card border border-border bg-surface">
            <Table caption={t("evx.col.questions")}>
              <THead>
                <tr>
                  <Th className="hidden sm:table-cell">{t("evx.dataset.key")}</Th>
                  <Th>{t("eval.edit.question")}</Th>
                  <Th className="hidden md:table-cell">{t("common.language")}</Th>
                  <Th>{t("eval.col.status")}</Th>
                  <Th>
                    <span className="sr-only">{t("evx.col.actions")}</span>
                  </Th>
                </tr>
              </THead>
              <TBody>
                {shown.map((item) => {
                  const checked = checkByKey.get(item.key);
                  return (
                    <Tr key={item.id}>
                      <Td className="hidden whitespace-nowrap align-top font-mono text-xs text-muted sm:table-cell">{item.key}</Td>
                      <Td className="max-w-xl align-top">
                        <p className="whitespace-pre-wrap break-words">{item.question}</p>
                        {item.reference_answer ? <p className="mt-1 whitespace-pre-wrap break-words text-xs text-muted">{item.reference_answer}</p> : null}
                        {item.tags.length > 0 ? (
                          <p className="mt-1 flex flex-wrap gap-1">
                            {item.tags.map((tag) => (
                              <Badge key={tag}>{tag}</Badge>
                            ))}
                          </p>
                        ) : null}
                        {checked && item.answerable && !checked.ok ? (
                          <p className="mt-1 text-xs text-danger">
                            {checked.evidence
                              .filter((e) => !e.found)
                              .map((e) => t("eval.dataset.checkMissing", { phrase: e.phrase }))
                              .join(" · ")}
                          </p>
                        ) : null}
                      </Td>
                      <Td className="hidden align-top md:table-cell">
                        <Badge>{t(`eval.lang.${item.language}`)}</Badge>
                      </Td>
                      <Td className="align-top">
                        {!item.answerable ? (
                          <Badge>{t("eval.dataset.notInMaterials")}</Badge>
                        ) : checked ? (
                          checked.ok ? (
                            <Badge tone="success">
                              <CheckCircle2 className="h-3 w-3" aria-hidden />
                              {t("eval.dataset.checkOk")}
                            </Badge>
                          ) : (
                            <Badge tone="danger">
                              <XCircle className="h-3 w-3" aria-hidden />
                              {t("evx.dataset.evidenceMissing")}
                            </Badge>
                          )
                        ) : (
                          <span className="text-faint">–</span>
                        )}
                      </Td>
                      <Td align="right" className="align-top">
                        <IconButton label={`${t("common.edit")}: ${item.key}`} onClick={() => setEditing(item)}>
                          <Pencil className="h-3.5 w-3.5" aria-hidden />
                        </IconButton>
                      </Td>
                    </Tr>
                  );
                })}
              </TBody>
            </Table>
          </div>
        )}
      </div>

      <Dialog open={editing !== null} onClose={() => setEditing(null)} title={t("eval.edit.title")} wide>
        {editing ? (
          <EditForm
            key={editing.id}
            datasetId={datasetId}
            item={editing}
            onSaved={() => {
              setEditing(null);
              setCheck(null);
              void load();
            }}
            onCancel={() => setEditing(null)}
          />
        ) : null}
      </Dialog>
    </>
  );
}

function EditForm({
  datasetId,
  item,
  onSaved,
  onCancel,
}: {
  datasetId: string;
  item: EvalCase;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const [question, setQuestion] = useState(item.question);
  const [reference, setReference] = useState(item.reference_answer ?? "");
  const [answerable, setAnswerable] = useState(item.answerable);
  const [evidence, setEvidence] = useState(evidenceToText(item.evidence));
  const [tags, setTags] = useState(item.tags.join(", "));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setMessage(null);
    try {
      await api(`/eval/datasets/${datasetId}/cases/${item.id}`, {
        method: "PATCH",
        body: {
          question,
          reference_answer: reference,
          answerable,
          evidence: textToEvidence(evidence),
          tags: tags
            .split(",")
            .map((tag) => tag.trim())
            .filter(Boolean),
        },
      });
      toast.success(t("evx.dataset.saved"));
      onSaved();
    } catch (caught) {
      setMessage(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <FormRow label={t("eval.edit.question")} htmlFor="edit-question">
        <Textarea id="edit-question" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} />
      </FormRow>
      <FormRow label={t("eval.result.reference")} htmlFor="edit-reference">
        <Textarea id="edit-reference" rows={3} value={reference} onChange={(e) => setReference(e.target.value)} />
      </FormRow>
      <label className="flex items-center gap-2 text-[13px]">
        <input type="checkbox" checked={answerable} onChange={(e) => setAnswerable(e.target.checked)} className="h-4 w-4 accent-primary" />
        {t("eval.edit.answerable")}
      </label>
      <FormRow label={t("eval.edit.evidence")} htmlFor="edit-evidence" hint={t("evx.dataset.evidenceHint")}>
        <Textarea id="edit-evidence" rows={3} value={evidence} onChange={(e) => setEvidence(e.target.value)} spellCheck={false} className="font-mono" />
      </FormRow>
      <FormRow label={t("eval.edit.tags")} htmlFor="edit-tags">
        <Input id="edit-tags" value={tags} onChange={(e) => setTags(e.target.value)} />
      </FormRow>
      {message ? (
        <p role="alert" className="text-sm text-danger">
          {message}
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" disabled={busy} onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" loading={busy} disabled={!question.trim()}>
          {t("common.save")}
        </Button>
      </div>
    </form>
  );
}
