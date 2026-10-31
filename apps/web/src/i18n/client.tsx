"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { Locale } from "./config";
import { makeT, type Messages, type TFunction } from "./translate";

type Value = { locale: Locale; t: TFunction };
const I18nContext = createContext<Value | null>(null);

export function I18nProvider({
  locale,
  messages,
  children,
}: {
  locale: Locale;
  messages: Messages;
  children: ReactNode;
}) {
  const value = useMemo(() => ({ locale, t: makeT(messages) }), [locale, messages]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

function useI18n(): Value {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useT must be used inside <I18nProvider>.");
  return value;
}

export function useT(): TFunction {
  return useI18n().t;
}

export function useLocale(): Locale {
  return useI18n().locale;
}
