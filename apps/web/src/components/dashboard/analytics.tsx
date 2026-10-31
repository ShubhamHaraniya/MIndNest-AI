"use client";

import clsx from "clsx";
import { BookOpenCheck, Flame, Layers, Trophy } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useId } from "react";

import { Panel, PanelLink } from "@/components/kit/panel";
import { CountUp } from "@/components/motion/count-up";
import { Stagger, StaggerItem } from "@/components/motion/reveal";
import { useLocale, useT } from "@/i18n/client";
import { formatDay } from "@/lib/format";
import type { DashboardData } from "@/lib/types";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

// ----------------------------------------------------------------------------------- KPI strip

type Kpi = { icon: LucideIcon; label: string; node: React.ReactNode; hint?: string; tone: string; href?: string };

/** Four figures that count up the first time they scroll into view. */
export function KpiStrip({ data }: { data: DashboardData }) {
  const t = useT();
  const { total, done } = data.today_tasks;
  const average = data.stats.quiz_average;
  const items: Kpi[] = [
    {
      icon: Flame,
      label: t("home.kpi.streak"),
      node: <CountUp value={data.streak_days} />,
      hint: data.streak_days === 0 ? t("home.kpi.streakStart") : undefined,
      tone: "bg-warning-soft text-warning ring-warning/25",
    },
    {
      icon: BookOpenCheck,
      label: t("home.kpi.today"),
      node:
        total > 0 ? (
          <>
            <CountUp value={done} />/{total}
          </>
        ) : (
          "—"
        ),
      tone: "bg-success-soft text-success ring-success/25",
      href: "/planner",
    },
    {
      icon: Layers,
      label: t("home.kpi.cards"),
      node: <CountUp value={data.stats.revision_due} />,
      tone: "bg-info-soft text-info ring-info/25",
      href: "/quizzes",
    },
    {
      icon: Trophy,
      label: t("home.kpi.quiz"),
      node: average === null ? "—" : <CountUp value={Math.round(average * 100)} format={(n) => `${Math.round(n)}%`} />,
      tone: "bg-primary-soft text-brand ring-primary/25",
      href: "/quizzes",
    },
  ];
  return (
    <Stagger as="ul" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {items.map(({ icon: Icon, label, node, hint, tone, href }) => {
        const body = (
          <>
            <span className={clsx("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ring-1", tone)}>
              <Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="tabular block truncate font-display text-3xl leading-8">{node}</span>
              <span className="block truncate text-xs text-muted">{hint ? `${label} · ${hint}` : label}</span>
            </span>
          </>
        );
        return (
          <StaggerItem as="li" key={label}>
            {href ? (
              <Link href={href} className="glass card-hover spot flex items-center gap-3.5 rounded-card px-4 py-3.5">
                {body}
              </Link>
            ) : (
              <div className="glass spot flex items-center gap-3.5 rounded-card px-4 py-3.5">{body}</div>
            )}
          </StaggerItem>
        );
      })}
    </Stagger>
  );
}

// ------------------------------------------------------------------------------ study-time bars

/** Seven columns: what was planned as a faint column, what was finished as a lit one inside it. */
export function StudyBars({ week, today }: { week: DashboardData["study_week"]; today: string }) {
  const t = useT();
  const locale = useLocale();
  const doneTotal = week.reduce((sum, day) => sum + day.minutes_done, 0);
  const plannedTotal = week.reduce((sum, day) => sum + day.minutes_planned, 0);
  const peak = Math.max(1, ...week.map((day) => Math.max(day.minutes_done, day.minutes_planned)));
  const empty = doneTotal === 0 && plannedTotal === 0;

  return (
    <Panel
      id="study"
      title={t("dashboard.studyTitle")}
      description={t("dashboard.studyBody")}
      className="h-full"
      bodyClassName="px-4 pb-4 pt-5"
    >
      {empty ? (
        <p className="py-6 text-sm text-muted">{t("dashboard.studyEmpty")}</p>
      ) : (
        <>
          <div
            role="img"
            aria-label={t("dashboard.studyChartSummary", { done: doneTotal, planned: plannedTotal })}
            className="flex h-40 items-end gap-2"
          >
            {week.map((day, index) => {
              const plannedH = (day.minutes_planned / peak) * 100;
              const doneH = (day.minutes_done / peak) * 100;
              const isToday = day.date === today;
              return (
                <div key={day.date} className="flex h-full min-w-0 flex-1 flex-col justify-end gap-2" title={`${day.minutes_done}/${day.minutes_planned} ${t("dashboard.minShort")}`}>
                  <div className="relative flex min-h-0 flex-1 items-end">
                    <div
                      className={clsx("absolute inset-x-0 bottom-0 rounded-t-lg border border-b-0", isToday ? "border-primary/40 bg-primary-soft" : "border-border bg-surface-3/50")}
                      style={{ height: `${Math.max(plannedH, 3)}%` }}
                    />
                    <motion.div
                      className="absolute inset-x-0 bottom-0 rounded-t-lg bg-gradient-to-t from-primary to-accent"
                      style={{ boxShadow: doneH > 0 ? "0 0 14px -2px var(--primary)" : undefined }}
                      initial={{ height: 0 }}
                      whileInView={{ height: `${doneH}%` }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.9, delay: 0.06 * index, ease: EASE }}
                    />
                  </div>
                  <span className={clsx("truncate text-center text-[11px]", isToday ? "font-semibold text-brand" : "text-faint")}>
                    {formatDay(day.date, locale, { weekday: "narrow" })}
                  </span>
                </div>
              );
            })}
          </div>
          <ul className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
            <li className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-gradient-to-br from-primary to-accent" aria-hidden />
              {t("dashboard.chartDone")}
              <span className="tabular font-medium text-ink">{doneTotal}</span>
            </li>
            <li className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm border border-border bg-surface-3" aria-hidden />
              {t("dashboard.chartPlanned")}
              <span className="tabular font-medium text-ink">{plannedTotal}</span>
            </li>
          </ul>
        </>
      )}
    </Panel>
  );
}

// -------------------------------------------------------------------------------- quiz trend

/** The last quiz scores as a line that draws itself, with a soft fill under it. */
export function QuizTrend({ trend }: { trend: DashboardData["quiz_trend"] }) {
  const t = useT();
  const reduce = useReducedMotion();
  const id = useId();
  const W = 320;
  const H = 150;
  const padX = 14;
  const padTop = 14;
  const padBottom = 18;
  const n = trend.length;
  const x = (i: number) => (n === 1 ? W / 2 : padX + (i * (W - padX * 2)) / (n - 1));
  const y = (percent: number) => padTop + (1 - Math.max(0, Math.min(100, percent)) / 100) * (H - padTop - padBottom);
  const points = trend.map((item, i) => ({ x: x(i), y: y(item.percent), item }));
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const area = n > 1 ? `${line} L${points[n - 1].x.toFixed(1)},${H - padBottom} L${points[0].x.toFixed(1)},${H - padBottom} Z` : "";
  const last = trend[n - 1];

  return (
    <Panel
      id="trend"
      title={t("dashboard.trendTitle")}
      description={t("dashboard.trendBody")}
      className="h-full"
      action={n > 0 ? <PanelLink href="/quizzes">{t("wb.weak.practise")}</PanelLink> : undefined}
      bodyClassName="px-4 pb-4 pt-4"
    >
      {n === 0 ? (
        <p className="py-6 text-sm text-muted">{t("dashboard.trendEmpty")}</p>
      ) : (
        <>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="h-auto w-full overflow-visible"
            role="img"
            aria-label={t("dashboard.trendSummary", { count: n, last: Math.round(last.percent) })}
          >
            <defs>
              <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.32" />
                <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
              </linearGradient>
              <linearGradient id={`${id}-line`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="var(--accent)" />
                <stop offset="100%" stopColor="var(--primary)" />
              </linearGradient>
            </defs>
            {[0, 50, 100].map((g) => (
              <g key={g}>
                <line x1={padX} x2={W - padX} y1={y(g)} y2={y(g)} stroke="var(--border)" strokeDasharray="3 5" />
                <text x={W - padX} y={y(g) - 4} textAnchor="end" fontSize="9" fill="var(--text-faint)">
                  {g}
                </text>
              </g>
            ))}
            {area ? (
              <motion.path
                d={area}
                fill={`url(#${id}-fill)`}
                initial={{ opacity: reduce ? 1 : 0 }}
                whileInView={{ opacity: 1 }}
                viewport={{ once: true }}
                transition={{ duration: 0.9, delay: 0.5 }}
              />
            ) : null}
            {n > 1 ? (
              <motion.path
                d={line}
                fill="none"
                stroke={`url(#${id}-line)`}
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ filter: "drop-shadow(0 0 6px var(--primary))" }}
                initial={{ pathLength: reduce ? 1 : 0 }}
                whileInView={{ pathLength: 1 }}
                viewport={{ once: true }}
                transition={{ duration: 1.3, ease: EASE }}
              />
            ) : null}
            {points.map((p, i) => (
              <motion.circle
                key={p.item.attempt_id}
                cx={p.x}
                cy={p.y}
                r={i === n - 1 ? 5 : 3.5}
                fill={i === n - 1 ? "var(--primary)" : "var(--surface)"}
                stroke="var(--primary)"
                strokeWidth={2}
                initial={{ opacity: reduce ? 1 : 0, scale: reduce ? 1 : 0.4 }}
                whileInView={{ opacity: 1, scale: 1 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: 0.25 + i * (1 / Math.max(n, 1)) * 0.9 }}
                style={{ transformBox: "fill-box", transformOrigin: "center" }}
              >
                <title>{`${p.item.title}: ${Math.round(p.item.percent)}%`}</title>
              </motion.circle>
            ))}
          </svg>
          <p className="mt-3 flex items-baseline gap-2 text-xs text-muted">
            <span className="tabular font-display text-2xl text-ink">
              <CountUp value={Math.round(last.percent)} format={(v) => `${Math.round(v)}%`} />
            </span>
            <span className="truncate">{last.title}</span>
          </p>
        </>
      )}
    </Panel>
  );
}
