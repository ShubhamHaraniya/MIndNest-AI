"use client";

import { useState } from "react";

import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { Panel } from "@/components/kit/panel";
import { useToast } from "@/components/kit/toast";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { GroupDetail, GroupPerson } from "@/lib/types";

import { InvitePanel } from "./invitations";
import { isAdminRole } from "./model";

/** Who is in the group and what they may do. The owner makes admins; owners and admins remove
 *  members (an admin cannot remove another admin, and nobody removes the owner). */
export function MembersTab({ group, onChanged }: { group: GroupDetail; onChanged: () => void }) {
  const t = useT();
  const toast = useToast();
  const [removing, setRemoving] = useState<GroupPerson | null>(null);
  const [changing, setChanging] = useState<string | null>(null);

  const isOwner = group.role === "owner";
  const canRemove = (person: GroupPerson) =>
    !person.is_me && (isOwner ? person.role !== "owner" : group.role === "admin" && person.role === "member");

  async function setRole(person: GroupPerson, role: "admin" | "member") {
    setChanging(person.user_id);
    try {
      await api(`/groups/${group.id}/members/${person.user_id}`, { method: "PATCH", body: { role } });
      toast.success(t(role === "admin" ? "gc.members.nowAdmin" : "gc.members.nowMember", { name: person.display_name }));
      onChanged();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    } finally {
      setChanging(null);
    }
  }

  async function remove() {
    if (!removing) return;
    try {
      await api(`/groups/${group.id}/members/${removing.user_id}`, { method: "DELETE" });
      toast.success(t("gc.members.removed", { name: removing.display_name }));
      onChanged();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  return (
    <div className="space-y-4">
      <Panel id="group-members" title={`${t("lib.members.title")} (${group.members.length})`} description={t("gc.members.rules")}>
        <ul className="divide-y divide-border px-3.5">
          {group.members.map((person) => (
            <li key={person.user_id} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm">
              <span className="min-w-0 break-words">
                {person.display_name}
                {person.is_me ? <span className="text-muted"> {t("lib.members.you")}</span> : null}
              </span>
              <span className="flex shrink-0 flex-wrap items-center gap-2">
                <Badge tone={person.role === "owner" ? "brand" : person.role === "admin" ? "info" : "neutral"}>
                  {t(`lib.role.${person.role}`)}
                </Badge>
                {isOwner && person.role !== "owner" ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={changing === person.user_id}
                    onClick={() => void setRole(person, person.role === "admin" ? "member" : "admin")}
                  >
                    {person.role === "admin" ? t("gc.members.makeMember") : t("gc.members.makeAdmin")}
                  </Button>
                ) : null}
                {canRemove(person) ? (
                  <Button variant="ghost" size="sm" onClick={() => setRemoving(person)}>
                    {t("lib.members.remove")}
                  </Button>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      </Panel>

      {isAdminRole(group.role) ? <InvitePanel groupId={group.id} isOwner={isOwner} /> : null}

      <ConfirmDialog
        open={removing !== null}
        title={t("lib.confirm.remove_member", { name: removing?.display_name ?? "" })}
        description={t("lib.confirm.remove_member_text")}
        confirmLabel={t("lib.members.remove")}
        onConfirm={remove}
        onClose={() => setRemoving(null)}
      />
    </div>
  );
}
