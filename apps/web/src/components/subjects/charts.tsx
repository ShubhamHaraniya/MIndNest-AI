"use client";

import { useState } from "react";

import { useLocale, useT } from "@/i18n/client";
import { bcp47, formatDay, percent } from "@/lib/format";

import type { AttemptPoint, WeekPoint } from "./model";

const W = 600;
const LEFT = 36;
const RIGHT = 12;

/** Quiz scores over time: one thin line, one dot per attempt, a recessive grid at 0, 50 and 100%.
 *  Hovering (or tabbing to) a dot shows its quiz, date and score above the chart; with nothing
 *  hovered the newest attempt is shown. A table of the same numbers is offered by the tab. */
export function ScoreChart({ attempts }: { attempts: AttemptPoint[] }) {
  const t = useT();
  const locale = useLocale();
  const [active, setActive] = useState<number | null>(null);

  const H = 170;
  const TOP = 10;
  const BOTTOM = 26;
  const inner = H - TOP - BOTTOM;
  const x = (i: number) => (attempts.length === 1 ? (LEFT + W - RIGHT) / 2 : LEFT + (i * (W - LEFT - RIGHT)) / (attempts.length - 1));
  const y = (value: number) => TOP + (1 - value) * inner;
  const shown = attempts[active ?? attempts.length - 1];
  const when = (iso: string) => new Intl.DateTimeFormat(bcp47(locale), { day: "numeric", month: "short" }).format(new Date(iso));

  return (
    <figure className="px-3.5 py-3">
      <figcaption className="mb-2 min-h-[2.5rem] text-[13px]" aria-live="polite">
        <span className="block truncate font-medium">{shown.quiz_title}</span>
        <span className="tabular text-muted">
          {percent(shown.percent)} · {t("sj.an.points", { points: Math.round(shown.points * 10) / 10, total: shown.total })} ·{" "}
          {when(shown.finished_at)}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("sj.an.scoresChart")} className="h-auto w-full overflow-visible">
        {[0, 0.5, 1].map((tick) => (
          <g key={tick}>
            <line x1={LEFT} x2={W - RIGHT} y1={y(tick)} y2={y(tick)} className="stroke-border" strokeWidth={1} />
            <text x={LEFT - 6} y={y(tick) + 4} textAnchor="end" className="fill-faint text-[11px]">
              {Math.round(tick * 100)}%
            </text>
          </g>
        ))}
        {attempts.length > 1 ? (
          <polyline
            points={attempts.map((a, i) => `${x(i)},${y(a.percent)}`).join(" ")}
            fill="none"
            className="stroke-primary"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ) : null}
        {attempts.map((a, i) => (
          <g key={a.attempt_id}>
            <circle
              cx={x(i)}
              cy={y(a.percent)}
              r={active === i || (active === null && i === attempts.length - 1) ? 5 : 4}
              className="fill-primary stroke-surface"
              strokeWidth={2}
            />
            {/* A larger invisible target than the dot, so it is easy to hover and tab to. */}
            <circle
              cx={x(i)}
              cy={y(a.percent)}
              r={12}
              fill="transparent"
              tabIndex={0}
              role="img"
              aria-label={`${a.quiz_title}: ${percent(a.percent)}, ${when(a.finished_at)}`}
              onMouseEnter={() => setActive(i)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              className="cursor-pointer outline-none focus-visible:stroke-primary"
            />
          </g>
        ))}
        <text x={LEFT} y={H - 6} className="fill-faint text-[11px]">
          {when(attempts[0].finished_at)}
        </text>
        {attempts.length > 1 ? (
          <text x={W - RIGHT} y={H - 6} textAnchor="end" className="fill-faint text-[11px]">
            {when(attempts[attempts.length - 1].finished_at)}
          </text>
        ) : null}
      </svg>
    </figure>
  );
}

/** Answers marked per week for the last weeks, as thin bars with a rounded top. Weeks without
 *  practice stay empty (a short baseline tick), never hidden, so a gap reads as a gap. */
export function WeeklyChart({ weeks }: { weeks: WeekPoint[] }) {
  const t = useT();
  const locale = useLocale();
  const [active, setActive] = useState<number | null>(null);

  const H = 150;
  const TOP = 8;
  const BOTTOM = 24;
  const inner = H - TOP - BOTTOM;
  const max = Math.max(1, ...weeks.map((w) => w.answers));
  const slot = (W - LEFT - RIGHT) / weeks.length;
  const bar = Math.min(28, slot * 0.5);
  const current = active ?? weeks.length - 1;
  const week = weeks[current];
  const label = (iso: string) => formatDay(iso, locale, { day: "numeric", month: "short" });

  return (
    <figure className="px-3.5 py-3">
      <figcaption className="mb-2 min-h-[2.5rem] text-[13px]" aria-live="polite">
        <span className="block font-medium">{t("sj.an.weekOf", { date: label(week.week_start) })}</span>
        <span className="tabular text-muted">
          {week.answers === 0
            ? t("sj.an.noPractice")
            : t("sj.an.weekDetail", { quizzes: week.attempts, answers: week.answers, accuracy: percent(week.accuracy) })}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("sj.an.weeksChart")} className="h-auto w-full overflow-visible">
        <line x1={LEFT} x2={W - RIGHT} y1={TOP + inner} y2={TOP + inner} className="stroke-border-strong" strokeWidth={1} />
        <line x1={LEFT} x2={W - RIGHT} y1={TOP} y2={TOP} className="stroke-border" strokeWidth={1} />
        <text x={LEFT - 6} y={TOP + 4} textAnchor="end" className="fill-faint text-[11px]">
          {max}
        </text>
        <text x={LEFT - 6} y={TOP + inner + 4} textAnchor="end" className="fill-faint text-[11px]">
          0
        </text>
        {weeks.map((w, i) => {
          const cx = LEFT + slot * i + slot / 2;
          const height = w.answers === 0 ? 0 : Math.max(3, (w.answers / max) * inner);
          const top = TOP + inner - height;
          const r = Math.min(4, height);
          return (
            <g key={w.week_start}>
              {height > 0 ? (
                <path
                  d={`M${cx - bar / 2},${TOP + inner} V${top + r} Q${cx - bar / 2},${top} ${cx - bar / 2 + r},${top} H${cx + bar / 2 - r} Q${cx + bar / 2},${top} ${cx + bar / 2},${top + r} V${TOP + inner} Z`}
                  className="fill-primary"
                  opacity={current === i ? 1 : 0.6}
                />
              ) : null}
              <rect
                x={cx - slot / 2}
                y={TOP}
                width={slot}
                height={inner + BOTTOM - 6}
                fill="transparent"
                tabIndex={0}
                role="img"
                aria-label={`${t("sj.an.weekOf", { date: label(w.week_start) })}: ${w.answers}`}
                onMouseEnter={() => setActive(i)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(i)}
                onBlur={() => setActive(null)}
                className="cursor-pointer outline-none focus-visible:stroke-primary"
              />
              {i % 2 === weeks.length % 2 || weeks.length <= 4 ? (
                <text x={cx} y={H - 6} textAnchor="middle" className="fill-faint text-[11px]">
                  {label(w.week_start)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
