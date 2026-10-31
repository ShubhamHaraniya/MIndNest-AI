"use client";

import { motion, useReducedMotion } from "motion/react";

import { Panel } from "@/components/kit/panel";
import { useT } from "@/i18n/client";

import { NO_MODULE, type ModuleProgress } from "./model";

const W = 640;
const H = 340;
const CX = W / 2;
const CY = H / 2;
const RX = 235;
const RY = 118;
const MAX_NODES = 14;

function colourOf(row: ModuleProgress): string {
  if (row.weak) return "var(--danger)";
  if (row.accuracy === null) return "var(--text-faint)";
  return row.accuracy >= 0.8 ? "var(--primary)" : "var(--warning)";
}

function short(text: string, max = 16): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** The course as a constellation: the course in the middle, each module around it. A module's size is how
 *  many files it holds and its colour is how well the student is doing on it. Drawn for the eye; the table
 *  below it is the accessible version, so this picture is hidden from screen readers. */
export function TopicMap({
  courseName,
  modules,
  onOpen,
}: {
  courseName: string;
  modules: ModuleProgress[];
  onOpen: (module: string) => void;
}) {
  const t = useT();
  const reduce = useReducedMotion();
  const items = [...modules].sort((a, b) => b.documents - a.documents).slice(0, MAX_NODES);
  const n = items.length;

  const nodes = items.map((row, index) => {
    const angle = n === 1 ? 0 : -Math.PI / 2 + (2 * Math.PI * index) / n;
    return {
      row,
      x: CX + RX * Math.cos(angle),
      y: CY + RY * Math.sin(angle),
      r: 17 + Math.min(row.documents, 12) * 1.5,
      colour: colourOf(row),
      delay: 0.15 + index * 0.06,
    };
  });

  return (
    <Panel id="topic-map" title={t("sj.overview.modules")} bodyClassName="px-3 pb-3 pt-1">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" aria-hidden focusable="false">
        <defs>
          <radialGradient id="topic-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.55" />
            <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx={CX} cy={CY} rx={RX} ry={RY} fill="none" stroke="var(--border)" strokeDasharray="3 7" />
        <circle cx={CX} cy={CY} r={70} fill="url(#topic-core)" />

        {nodes.map((node) => (
          <motion.line
            key={`line-${node.row.module ?? NO_MODULE}`}
            x1={CX}
            y1={CY}
            x2={node.x}
            y2={node.y}
            stroke={node.colour}
            strokeOpacity={0.45}
            strokeWidth={1.25}
            initial={{ pathLength: reduce ? 1 : 0 }}
            whileInView={{ pathLength: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8, delay: node.delay, ease: [0.22, 1, 0.36, 1] }}
          />
        ))}

        <circle cx={CX} cy={CY} r={36} fill="var(--surface-2)" stroke="var(--primary)" strokeWidth={2} style={{ filter: "drop-shadow(0 0 10px var(--primary))" }} />
        <text x={CX} y={CY + 4} textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--text)">
          {short(courseName, 11)}
        </text>

        {nodes.map((node) => (
          <motion.g
            key={node.row.module ?? NO_MODULE}
            className="cursor-pointer"
            onClick={() => onOpen(node.row.module ?? NO_MODULE)}
            initial={{ opacity: reduce ? 1 : 0, scale: reduce ? 1 : 0.4 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: node.delay + 0.25, ease: [0.22, 1, 0.36, 1] }}
            style={{ transformBox: "fill-box", transformOrigin: "center" }}
          >
            <circle
              cx={node.x}
              cy={node.y}
              r={node.r}
              fill={`color-mix(in srgb, ${node.colour} 18%, var(--surface))`}
              stroke={node.colour}
              strokeWidth={2}
              style={{ filter: `drop-shadow(0 0 6px ${node.colour})` }}
            />
            <text x={node.x} y={node.y + 4} textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--text)">
              {node.row.documents}
            </text>
            <text x={node.x} y={node.y + node.r + 15} textAnchor="middle" fontSize="11" fill="var(--text-muted)">
              {short(node.row.module ?? t("sj.module.none"))}
            </text>
          </motion.g>
        ))}
      </svg>
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 pb-1 text-xs text-muted" aria-hidden>
        <li className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-primary" />
          80%+
        </li>
        <li className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-warning" />
          &lt; 80%
        </li>
        <li className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-danger" />
          {t("sj.progress.weak")}
        </li>
        <li className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-faint" />
          {t("sj.progress.notPractised")}
        </li>
      </ul>
    </Panel>
  );
}
