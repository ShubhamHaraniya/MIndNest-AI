import type { Locale } from "@/i18n/config";

import en from "@/content/guide/en.json";
import gu from "@/content/guide/gu.json";
import hi from "@/content/guide/hi.json";

export type GuideSection = {
  id: string;
  title: string;
  body: string[];
  steps?: string[];
  tip?: string;
};

export type Guide = {
  title: string;
  intro: string;
  contents: string;
  stepsLabel: string;
  tipLabel: string;
  topLabel: string;
  sections: GuideSection[];
};

const GUIDES: Record<Locale, Guide> = { en, hi, gu };

export function getGuide(locale: Locale): Guide {
  return GUIDES[locale] ?? GUIDES.en;
}
