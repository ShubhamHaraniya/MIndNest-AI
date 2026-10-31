"use client";

import { ArrowRight, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { MyInvitations } from "@/components/groups/invitations";
import { Badge } from "@/components/kit/badge";
import { EmptyState } from "@/components/kit/states";
import { SkeletonText } from "@/components/kit/skeleton";
import { Alert, Button, Field } from "@/components/ui";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Group } from "@/lib/types";

/** A stable colour for a group, from the five chart colours. */
function hueOf(id: string): number {
  let sum = 0;
  for (const char of id) sum = (sum + char.charCodeAt(0)) % 5;
  return sum + 1;
}

const textareaClass = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm placeholder:text-muted";

export function LibraryHub() {
  const t = useT();
  const router = useRouter();
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"create" | "join" | null>(null);

  const load = useCallback(async () => {
    try {
      setGroups(await api<Group[]>("/groups"));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      {error ? <Alert>{error}</Alert> : null}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface px-4 py-3.5 shadow-card sm:px-5">
        <div className="flex min-w-0 max-w-2xl items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-brand">
            <Users className="h-5 w-5" strokeWidth={1.75} aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 className="font-semibold">{t("lib.title")}</h2>
            <p className="mt-0.5 text-sm text-muted">{t("lib.intro")}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setDialog("join")}>
            {t("lib.join.button")}
          </Button>
          <Button onClick={() => setDialog("create")}>{t("lib.create.button")}</Button>
        </div>
      </div>

      <MyInvitations onChanged={() => void load()} />

      {groups === null ? (
        error ? null : <SkeletonText lines={4} className="py-4" />
      ) : groups.length === 0 ? (
        <EmptyState title={t("lib.empty")} />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {groups.map((group) => {
            const hue = hueOf(group.id);
            return (
              <li key={group.id} className="card-hover group relative flex flex-col rounded-card border border-border bg-surface p-5 shadow-card">
                <Link href={`/library/${group.id}`} className="absolute inset-0 z-0 rounded-card" aria-label={group.name} />
                <div className="pointer-events-none relative z-10 flex items-start gap-3">
                  <span
                    aria-hidden
                    className="font-display flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-lg"
                    style={{
                      color: `var(--chart-${hue})`,
                      background: `color-mix(in srgb, var(--chart-${hue}) 14%, var(--surface))`,
                    }}
                  >
                    {group.name.trim().charAt(0).toUpperCase() || "?"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <h3 className="break-words text-[15px] font-semibold leading-5">{group.name}</h3>
                    <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
                      <Users className="h-3.5 w-3.5" aria-hidden />
                      {t("lib.card.members", { count: group.member_count })} · {t("lib.card.files", { count: group.item_count })}
                    </p>
                  </div>
                  <Badge tone="brand">{t(`lib.role.${group.role}`)}</Badge>
                </div>
                {group.description ? (
                  <p className="pointer-events-none relative z-10 mt-3 line-clamp-2 text-sm text-muted">{group.description}</p>
                ) : null}
                <p className="pointer-events-none relative z-10 mt-4 inline-flex items-center gap-1 text-sm font-medium text-brand">
                  {t("lib.card.open")}
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5 rtl:rotate-180 rtl:group-hover:-translate-x-0.5" aria-hidden />
                </p>
              </li>
            );
          })}
        </ul>
      )}

      <CreateDialog
        open={dialog === "create"}
        onClose={() => setDialog(null)}
        onDone={(id) => {
          setDialog(null);
          router.push(`/library/${id}`);
        }}
      />
      <JoinDialog
        open={dialog === "join"}
        onClose={() => setDialog(null)}
        onDone={(id) => {
          setDialog(null);
          router.push(`/library/${id}`);
        }}
      />
    </div>
  );
}

function CreateDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (id: string) => void }) {
  const t = useT();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const group = await api<Group>("/groups", { method: "POST", body: { name, description } });
      setName("");
      setDescription("");
      onDone(group.id);
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("lib.create.title")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert>{error}</Alert> : null}
        <Field
          label={t("lib.create.name")}
          hint={t("lib.create.name_hint")}
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={80}
          minLength={2}
          required
        />
        <div>
          <label htmlFor="group-description" className="mb-1.5 block text-sm font-medium">
            {t("lib.create.description")}
          </label>
          <textarea
            id="group-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={300}
            rows={3}
            className={textareaClass}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={name.trim().length < 2}>
            {t("lib.create.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function JoinDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (id: string) => void }) {
  const t = useT();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const group = await api<Group>("/groups/join", { method: "POST", body: { code } });
      setCode("");
      onDone(group.id);
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("lib.join.title")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert>{error}</Alert> : null}
        <Field
          label={t("lib.join.code")}
          hint={t("lib.join.hint")}
          value={code}
          onChange={(event) => setCode(event.target.value)}
          maxLength={40}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          required
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={code.trim().length < 10}>
            {t("lib.join.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
