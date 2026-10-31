"use client";

import { Mail, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { FormRow, Input, Select } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { useToast } from "@/components/kit/toast";
import { IconButton } from "@/components/subjects/bits";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Group, GroupInvitation, MyInvitation } from "@/lib/types";

import { formatDate } from "./model";

/** Invite people by email and see who has not answered yet. Owners and admins only. */
export function InvitePanel({ groupId, isOwner }: { groupId: string; isOwner: boolean }) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [pending, setPending] = useState<GroupInvitation[] | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"member" | "admin">("member");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPending(await api<GroupInvitation[]>(`/groups/${groupId}/invitations`));
    } catch (caught) {
      setFailure(errorMessage(caught, t));
    }
  }, [groupId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !email.trim()) return;
    setBusy(true);
    setFailure(null);
    try {
      const sent = await api<GroupInvitation>(`/groups/${groupId}/invitations`, {
        method: "POST",
        body: { email: email.trim(), role: isOwner ? role : "member" },
      });
      setEmail("");
      toast.success(t("gc.invite.sent", { email: sent.email }));
      await load();
    } catch (caught) {
      setFailure(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(invitation: GroupInvitation) {
    try {
      await api(`/groups/${groupId}/invitations/${invitation.id}`, { method: "DELETE" });
      toast.info(t("gc.invite.revoked", { email: invitation.email }));
      await load();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  return (
    <Panel id="group-invitations" title={t("gc.invite.title")} bodyClassName="p-3.5">
      <p className="mb-3 max-w-2xl text-[13px] text-muted">{t("gc.invite.intro")}</p>
      <form onSubmit={(event) => void submit(event)} className="flex flex-wrap items-end gap-3">
        <FormRow label={t("gc.invite.email")} htmlFor="invite-email" className="min-w-[14rem] flex-1">
          <Input
            id="invite-email"
            type="email"
            autoComplete="off"
            value={email}
            maxLength={254}
            placeholder={t("gc.invite.placeholder")}
            onChange={(event) => setEmail(event.target.value)}
          />
        </FormRow>
        {isOwner ? (
          <FormRow label={t("gc.invite.role")} htmlFor="invite-role">
            <Select id="invite-role" value={role} onChange={(event) => setRole(event.target.value as "member" | "admin")}>
              <option value="member">{t("lib.role.member")}</option>
              <option value="admin">{t("lib.role.admin")}</option>
            </Select>
          </FormRow>
        ) : null}
        <Button type="submit" loading={busy} disabled={!email.trim()}>
          <Mail className="h-4 w-4" aria-hidden />
          {t("gc.invite.send")}
        </Button>
      </form>
      {failure ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {failure}
        </p>
      ) : null}

      <div className="mt-4">
        <h3 className="text-[13px] font-medium">{t("gc.invite.open")}</h3>
        {pending === null ? null : pending.length === 0 ? (
          <p className="mt-1 text-[13px] text-muted">{t("gc.invite.none")}</p>
        ) : (
          <ul className="mt-1 divide-y divide-border">
            {pending.map((invitation) => (
              <li key={invitation.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="block break-all">{invitation.email}</span>
                  <span className="block text-xs text-muted">
                    {t("gc.invite.expires", { date: formatDate(invitation.expires_at, locale) })}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {invitation.role === "admin" ? <Badge tone="brand">{t("lib.role.admin")}</Badge> : null}
                  <IconButton label={t("gc.invite.revoke", { email: invitation.email })} danger onClick={() => void revoke(invitation)}>
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </IconButton>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}

/** Invitations sent to the signed-in email address, with Accept and Decline. Shows nothing when
 *  there are none. */
export function MyInvitations({ onChanged }: { onChanged: () => void }) {
  const t = useT();
  const toast = useToast();
  const router = useRouter();
  const [items, setItems] = useState<MyInvitation[]>([]);
  const [working, setWorking] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await api<MyInvitation[]>("/group-invitations"));
    } catch {
      setItems([]); // the groups list below still works; the invitations are just not shown
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function answer(invitation: MyInvitation, accept: boolean) {
    setWorking(invitation.id);
    try {
      if (accept) {
        const group = await api<Group>(`/group-invitations/${invitation.id}/accept`, { method: "POST" });
        toast.success(t("gc.mine.joined", { name: group.name }));
        onChanged();
        router.push(`/library/${group.id}`);
        return;
      }
      await api(`/group-invitations/${invitation.id}/decline`, { method: "POST" });
      toast.info(t("gc.mine.declined", { name: invitation.group_name }));
      await load();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
      await load();
    } finally {
      setWorking(null);
    }
  }

  if (items.length === 0) return null;

  return (
    <Panel id="my-invitations" title={t("gc.mine.title", { count: items.length })} bodyClassName="px-3.5">
      <ul className="divide-y divide-border">
        {items.map((invitation) => (
          <li key={invitation.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <p className="break-words font-medium">{invitation.group_name}</p>
              <p className="text-xs text-muted">
                {t("gc.mine.from", { name: invitation.invited_by_name })}
                {invitation.role === "admin" ? ` · ${t("gc.mine.asAdmin")}` : ""}
              </p>
              {invitation.group_description ? (
                <p className="mt-0.5 line-clamp-2 text-[13px] text-muted">{invitation.group_description}</p>
              ) : null}
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" disabled={working === invitation.id} onClick={() => void answer(invitation, false)}>
                {t("gc.mine.decline")}
              </Button>
              <Button size="sm" loading={working === invitation.id} onClick={() => void answer(invitation, true)}>
                {t("gc.mine.accept")}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
