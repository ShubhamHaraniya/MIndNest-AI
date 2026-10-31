"use client";

import { useEffect, useId, useState } from "react";

import { FormRow, Input } from "@/components/kit";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";

type Suggestion = { name: string; students: number };

/** The student's institution, typed freely. Names that two or more students already use are
 *  offered as suggestions so "IIT Delhi" is not spelled five ways. */
export function InstitutionField({
  value,
  onChange,
  hint,
  id,
}: {
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  id?: string;
}) {
  const t = useT();
  const generated = useId();
  const inputId = id ?? generated;
  const listId = `${inputId}-list`;
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);

  useEffect(() => {
    const query = value.trim();
    if (query.length < 2) {
      setSuggestions([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api<Suggestion[]>(`/library/institutions?q=${encodeURIComponent(query)}`, { signal: controller.signal })
        .then(setSuggestions)
        .catch(() => setSuggestions([]));
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [value]);

  return (
    <FormRow label={t("inst.label")} htmlFor={inputId} hint={hint ?? t("inst.hint")}>
      <Input
        id={inputId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        maxLength={120}
        list={listId}
        autoComplete="organization"
        placeholder={t("inst.placeholder")}
      />
      <datalist id={listId}>
        {suggestions.map((s) => (
          <option key={s.name} value={s.name} />
        ))}
      </datalist>
    </FormRow>
  );
}
