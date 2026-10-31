"use client";

import { useState, type FormEvent, type ReactNode } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { FormRow, Input, Select } from "@/components/kit/controls";
import { useToast } from "@/components/kit/toast";
import { useT } from "@/i18n/client";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Material, MaterialKind } from "@/lib/types";

import { KINDS, KIND_KEYS } from "./model";
import type { Resource } from "./use-resource";

export const MODULE_MAX = 80;

/** A module name box that suggests the course's existing modules, so spelling stays consistent. */
export function ModuleInput({
  id,
  value,
  onChange,
  modules,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  modules: string[];
}) {
  const t = useT();
  return (
    <>
      <Input
        id={id}
        list={`${id}-options`}
        value={value}
        maxLength={MODULE_MAX}
        placeholder={t("sj.module.placeholder")}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
      />
      <datalist id={`${id}-options`}>
        {modules.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
    </>
  );
}

/** Edit, retry and delete for the files of one course, with their dialogs. Shared by every tab
 *  and the preview pane so a change made anywhere shows up everywhere. */
export function useMaterialActions({
  materials,
  modules,
  onChanged,
  onRemoved,
}: {
  materials: Resource<Material[]>;
  modules: string[];
  /** Called after any change that moves a figure (module counts, readiness, accuracy). */
  onChanged: () => void;
  onRemoved: (material: Material) => void;
}): {
  edit: (material: Material) => void;
  retry: (material: Material) => Promise<void>;
  remove: (material: Material) => void;
  dialogs: ReactNode;
} {
  const t = useT();
  const toast = useToast();
  const [editing, setEditing] = useState<Material | null>(null);
  const [deleting, setDeleting] = useState<Material | null>(null);

  function replace(next: Material) {
    materials.setData((list) => list.map((item) => (item.id === next.id ? next : item)));
  }

  async function retry(material: Material) {
    try {
      replace(await api<Material>(`/materials/${material.id}/retry`, { method: "POST" }));
      toast.info(t("sj.toast.retrying", { name: material.filename }));
    } catch (caught) {
      // 409 means it is already running again; anything else is worth showing.
      if (!(caught instanceof ApiError && caught.status === 409)) toast.error(errorMessage(caught, t));
    }
    materials.reload();
  }

  async function confirmDelete() {
    if (!deleting) return;
    const target = deleting;
    try {
      await api(`/materials/${target.id}`, { method: "DELETE" });
      materials.setData((list) => list.filter((item) => item.id !== target.id));
      onRemoved(target);
      onChanged();
      toast.success(t("sj.toast.deleted", { name: target.filename }));
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  const dialogs = (
    <>
      <EditMaterialDialog
        material={editing}
        modules={modules}
        onClose={() => setEditing(null)}
        onSaved={(saved) => {
          replace(saved);
          setEditing(null);
          onChanged();
          toast.success(t("sj.toast.updated"));
        }}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("materials.deleteTitle", { name: deleting?.filename ?? "" })}
        description={t("materials.deleteBody")}
        confirmLabel={t("materials.delete")}
        onConfirm={confirmDelete}
        onClose={() => setDeleting(null)}
      />
    </>
  );

  return { edit: setEditing, retry, remove: setDeleting, dialogs };
}

function EditMaterialDialog({
  material,
  modules,
  onClose,
  onSaved,
}: {
  material: Material | null;
  modules: string[];
  onClose: () => void;
  onSaved: (material: Material) => void;
}) {
  const t = useT();
  return (
    <Dialog open={material !== null} onClose={onClose} title={t("sj.edit.title")}>
      {/* Keyed so the form starts from the file it was opened for. */}
      {material ? <EditForm key={material.id} material={material} modules={modules} onCancel={onClose} onSaved={onSaved} /> : null}
    </Dialog>
  );
}

function EditForm({
  material,
  modules,
  onCancel,
  onSaved,
}: {
  material: Material;
  modules: string[];
  onCancel: () => void;
  onSaved: (material: Material) => void;
}) {
  const t = useT();
  const [module, setModule] = useState(material.module ?? "");
  const [kind, setKind] = useState<MaterialKind>(material.kind);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const moduleChanged = module.trim() !== (material.module ?? "");
  const kindChanged = kind !== material.kind;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!moduleChanged && !kindChanged) return onCancel();
    setBusy(true);
    setError(null);
    const body: { module?: string | null; kind?: MaterialKind } = {};
    if (moduleChanged) body.module = module.trim() || null;
    if (kindChanged) body.kind = kind;
    try {
      onSaved(await api<Material>(`/materials/${material.id}`, { method: "PATCH", body }));
    } catch (caught) {
      setError(errorMessage(caught, t));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <p className="break-all text-[13px] text-muted">{material.filename}</p>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <FormRow label={t("sj.col.module")} htmlFor="edit-module" hint={t("sj.module.hint")}>
        <ModuleInput id="edit-module" value={module} onChange={setModule} modules={modules} />
      </FormRow>
      <FormRow label={t("sj.col.type")} htmlFor="edit-kind">
        <Select id="edit-kind" value={kind} onChange={(event) => setKind(event.target.value as MaterialKind)} className="w-full">
          {KINDS.map((value) => (
            <option key={value} value={value}>
              {t(KIND_KEYS[value])}
            </option>
          ))}
        </Select>
      </FormRow>
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="secondary" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" loading={busy} disabled={!moduleChanged && !kindChanged}>
          {t("common.save")}
        </Button>
      </div>
    </form>
  );
}
