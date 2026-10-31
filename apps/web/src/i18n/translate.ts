import en from "./messages/en.json";
import gu from "./messages/gu.json";
import hi from "./messages/hi.json";
import type { Locale } from "./config";

export type MessageKey = keyof typeof en;
export type Messages = Record<MessageKey, string>;
export type TFunction = (key: MessageKey, vars?: Record<string, string | number>) => string;

// English is the source of truth. A key missing from hi or gu falls back to English, so an
// untranslated string shows up in English instead of as an empty gap.
const CATALOGS: Record<Locale, Partial<Messages>> = { en, hi, gu };

export function getMessages(locale: Locale): Messages {
  return { ...(en as Messages), ...CATALOGS[locale] };
}

export function makeT(messages: Messages): TFunction {
  return (key, vars) => {
    const template = messages[key] ?? key;
    if (!vars) return template;
    return template.replace(/\{(\w+)\}/g, (match, name: string) =>
      name in vars ? String(vars[name]) : match,
    );
  };
}
