"use client";

import { ArrowRight } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useId, type ReactNode } from "react";

import { ButtonLink } from "@/components/kit/button";
import { CountUp } from "@/components/motion/count-up";
import { useT } from "@/i18n/client";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

/** The centre of the command center: today's progress as a large glowing ring, and the one thing to do
 *  next beside it. The ring draws itself once on load. */
export function FocusCard({
  icon,
  title,
  body,
  cta,
  href,
  done,
  total,
  minutesDone,
  minutesTotal,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  cta: string;
  href: string;
  done: number;
  total: number;
  minutesDone: number;
  minutesTotal: number;
}) {
  const t = useT();
  const reduce = useReducedMotion();
  const gradient = useId();
  const ratio = total > 0 ? done / total : 0;
  const size = 176;
  const stroke = 10;
  const r = (size - stroke) / 2;

  return (
    <section aria-labelledby="focus-title" className="glass sheen relative overflow-hidden rounded-3xl p-6 sm:p-8">
      <div
        aria-hidden
        className="pointer-events-none absolute -left-10 top-1/2 h-72 w-72 -translate-y-1/2 animate-glow-pulse rounded-full bg-primary/15 blur-3xl"
      />
      <div className="relative flex flex-col items-center gap-7 sm:flex-row sm:items-center sm:gap-9">
        <div
          role="img"
          aria-label={`${t("home.kpi.today")}: ${Math.round(ratio * 100)}%`}
          className="relative shrink-0"
          style={{ width: size, height: size }}
        >
          <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="var(--primary)" />
                <stop offset="100%" stopColor="var(--accent)" />
              </linearGradient>
            </defs>
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
            <circle cx={size / 2} cy={size / 2} r={r - 18} fill="none" stroke="var(--border)" strokeWidth={1} strokeDasharray="2 6" />
            <motion.circle
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={`url(#${gradient})`}
              strokeWidth={stroke}
              strokeLinecap="round"
              style={{ filter: "drop-shadow(0 0 8px var(--primary))" }}
              initial={{ pathLength: reduce ? ratio : 0 }}
              animate={{ pathLength: ratio }}
              transition={{ duration: 1.3, ease: EASE, delay: 0.2 }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
            <span className="font-display text-4xl leading-none">
              <CountUp value={Math.round(ratio * 100)} format={(n) => `${Math.round(n)}%`} />
            </span>
            <span className="mt-1.5 text-[11px] font-medium uppercase tracking-wider text-faint rtl:tracking-normal">{t("home.kpi.today")}</span>
          </div>
        </div>

        <div className="min-w-0 text-center sm:text-start">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-brand rtl:tracking-normal">{t("home.next.label")}</p>
          <div className="mt-3 flex items-start justify-center gap-3.5 sm:justify-start">
            <span className="mt-1 hidden h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-primary-soft text-brand ring-1 ring-primary/25 sm:flex [&>svg]:h-5 [&>svg]:w-5">
              {icon}
            </span>
            <h2 id="focus-title" className="font-display text-balance text-2xl leading-snug sm:text-3xl">
              {title}
            </h2>
          </div>
          <p className="mt-2 text-sm text-muted sm:ps-[3.625rem]">{body}</p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-4 sm:justify-start sm:ps-[3.625rem]">
            <ButtonLink href={href} size="lg">
              {cta}
              <ArrowRight className="h-4 w-4 rtl:rotate-180" aria-hidden />
            </ButtonLink>
            {total > 0 ? (
              <span className="tabular text-sm text-muted">
                {t("home.today.progress", { done, total })} · {minutesDone}/{minutesTotal} {t("dashboard.minShort")}
              </span>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
