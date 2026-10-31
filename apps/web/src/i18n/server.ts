import { cookies } from "next/headers";

import { DEFAULT_LOCALE, isLocale, LOCALE_COOKIE, type Locale } from "./config";
import { getMessages, makeT, type TFunction } from "./translate";

export async function getLocale(): Promise<Locale> {
  const value = (await cookies()).get(LOCALE_COOKIE)?.value;
  return isLocale(value) ? value : DEFAULT_LOCALE;
}

export async function getT(): Promise<{ t: TFunction; locale: Locale }> {
  const locale = await getLocale();
  return { t: makeT(getMessages(locale)), locale };
}
