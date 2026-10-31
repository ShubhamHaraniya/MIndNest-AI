"use client";

import clsx from "clsx";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";

import { useT } from "@/i18n/client";

// ---------------------------------------------------------------------------- the picture spec
// The server checks every `mindnest-diagram` block before it saves an answer (see
// `chatlogic.validate_diagram`). The shapes below are what that check produces. The text is drawn as
// SVG text, never as HTML, so a label can never run script.

type TreeNode = { value: string; left: TreeNode | null; right: TreeNode | null };
type TreeSpec = { type: "binary_tree"; title: string; root: TreeNode; steps: { highlight: string[]; note: string }[] };
type ListSpec = {
  type: "linked_list";
  title: string;
  nodes: string[];
  doubly: boolean;
  circular: boolean;
  steps: { highlight: number[]; note: string }[];
};
type GraphSpec = {
  type: "graph";
  title: string;
  directed: boolean;
  nodes: { id: string; label: string }[];
  edges: { from: string; to: string; weight: string | null }[];
  steps: { current: string | null; visited: string[]; frontier: string[]; note: string }[];
};
type ArraySpec = {
  type: "array";
  title: string;
  values: string[];
  steps: {
    values: string[];
    highlight: number[];
    swapped: number[];
    sorted: number[];
    pointers: Record<string, number>;
    note: string;
  }[];
};
export type DiagramSpec = TreeSpec | ListSpec | GraphSpec | ArraySpec;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string => (typeof value === "string" || typeof value === "number" ? String(value) : "");
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const texts = (value: unknown): string[] => list(value).map(text);
const indexes = (value: unknown): number[] =>
  list(value).filter((item): item is number => typeof item === "number" && Number.isInteger(item) && item >= 0);

function treeNode(value: unknown, depth = 0): TreeNode | null {
  if (!isRecord(value) || depth > 8) return null;
  return { value: text(value.value), left: treeNode(value.left, depth + 1), right: treeNode(value.right, depth + 1) };
}

/** Read a block's JSON into a drawing spec, or null when it is not one (the caller then shows the
 *  source as plain text). Only the fields the drawing needs are read. */
export function parseDiagram(source: string): DiagramSpec | null {
  let raw: unknown;
  try {
    raw = JSON.parse(source);
  } catch {
    return null;
  }
  if (!isRecord(raw)) return null;
  const title = text(raw.title);
  const steps = list(raw.steps).filter(isRecord);
  if (raw.type === "binary_tree") {
    const root = treeNode(raw.root);
    if (!root) return null;
    return { type: "binary_tree", title, root, steps: steps.map((s) => ({ highlight: texts(s.highlight), note: text(s.note) })) };
  }
  if (raw.type === "linked_list") {
    const nodes = texts(raw.nodes);
    if (nodes.length === 0) return null;
    return {
      type: "linked_list",
      title,
      nodes,
      doubly: raw.doubly === true,
      circular: raw.circular === true,
      steps: steps.map((s) => ({ highlight: indexes(s.highlight), note: text(s.note) })),
    };
  }
  if (raw.type === "graph") {
    const nodes = list(raw.nodes)
      .filter(isRecord)
      .map((n) => ({ id: text(n.id), label: text(n.label) || text(n.id) }));
    if (nodes.length === 0) return null;
    return {
      type: "graph",
      title,
      directed: raw.directed === true,
      nodes,
      edges: list(raw.edges)
        .filter(isRecord)
        .map((e) => ({ from: text(e.from), to: text(e.to), weight: text(e.weight) || null })),
      steps: steps.map((s) => ({
        current: s.current == null ? null : text(s.current),
        visited: texts(s.visited),
        frontier: texts(s.frontier),
        note: text(s.note),
      })),
    };
  }
  if (raw.type === "array") {
    const values = texts(raw.values);
    if (values.length === 0) return null;
    return {
      type: "array",
      title,
      values,
      steps: steps.map((s) => ({
        values: list(s.values).length === values.length ? texts(s.values) : values,
        highlight: indexes(s.highlight),
        swapped: indexes(s.swapped),
        sorted: indexes(s.sorted),
        pointers: isRecord(s.pointers)
          ? Object.fromEntries(Object.entries(s.pointers).filter((entry): entry is [string, number] => typeof entry[1] === "number"))
          : {},
        note: text(s.note),
      })),
    };
  }
  return null;
}

// ---------------------------------------------------------------------------------- the drawing

const PAD = 20;
const NEUTRAL = "fill-surface stroke-border-strong";
const MARKED = "fill-primary-soft stroke-primary";
const WARM = "fill-warning-soft stroke-warning";
const DONE = "fill-success-soft stroke-success";
const NOW = "fill-primary stroke-primary";

function labelWidth(label: string, min = 30): number {
  return Math.min(110, Math.max(min, 9 + label.length * 7.2));
}

function Arrowhead({ id }: { id: string }) {
  return (
    <defs>
      <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 z" className="fill-muted" />
      </marker>
    </defs>
  );
}

type Placed = { value: string; x: number; y: number; w: number; parent: Placed | null };

function placeTree(root: TreeNode): { nodes: Placed[]; width: number; height: number } {
  const nodes: Placed[] = [];
  let widest = 30;
  const measure = (node: TreeNode | null): void => {
    if (!node) return;
    widest = Math.max(widest, labelWidth(node.value));
    measure(node.left);
    measure(node.right);
  };
  measure(root);
  const slot = widest + 14;
  let order = 0;
  let deepest = 0;
  const walk = (node: TreeNode | null, depth: number, parent: Placed | null): void => {
    if (!node) return;
    // Left subtree first, so the in-order position is the horizontal position.
    const placed: Placed = { value: node.value, x: 0, y: PAD + depth * 58 + 16, w: labelWidth(node.value), parent };
    walk(node.left, depth + 1, placed);
    placed.x = PAD + order * slot + slot / 2;
    order += 1;
    nodes.push(placed);
    deepest = Math.max(deepest, depth);
    walk(node.right, depth + 1, placed);
  };
  walk(root, 0, null);
  return { nodes, width: PAD * 2 + order * slot, height: PAD * 2 + deepest * 58 + 32 };
}

function TreeDrawing({ spec, step }: { spec: TreeSpec; step: number | null }) {
  const layout = useMemo(() => placeTree(spec.root), [spec.root]);
  const marked = new Set(step !== null ? (spec.steps[step]?.highlight ?? []) : []);
  return (
    <svg viewBox={`0 0 ${layout.width} ${layout.height}`} width={layout.width} role="img" aria-label={spec.title} className="mx-auto h-auto max-w-full">
      {layout.nodes.map((n, i) =>
        n.parent ? <line key={`e${i}`} x1={n.parent.x} y1={n.parent.y} x2={n.x} y2={n.y} className="stroke-border-strong" strokeWidth={1.5} /> : null,
      )}
      {layout.nodes.map((n, i) => (
        <g key={`n${i}`}>
          <rect x={n.x - n.w / 2} y={n.y - 15} width={n.w} height={30} rx={15} className={marked.has(n.value) ? NOW : NEUTRAL} strokeWidth={1.5} />
          <text x={n.x} y={n.y} textAnchor="middle" dominantBaseline="central" fontSize={13} className={marked.has(n.value) ? "fill-white" : "fill-ink"}>
            {n.value}
          </text>
        </g>
      ))}
    </svg>
  );
}

function ListDrawing({ spec, step }: { spec: ListSpec; step: number | null }) {
  const arrow = useId().replace(/:/g, "");
  const box = 58;
  const gap = 40;
  const marked = new Set(step !== null ? (spec.steps[step]?.highlight ?? []) : []);
  const width = PAD * 2 + spec.nodes.length * box + (spec.nodes.length - 1) * gap + (spec.circular ? 0 : 34);
  const height = PAD * 2 + 34 + (spec.circular ? 34 : 0) + (spec.doubly ? 8 : 0);
  const midY = PAD + 17;
  const left = (i: number) => PAD + i * (box + gap);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} role="img" aria-label={spec.title} className="mx-auto h-auto max-w-full">
      <Arrowhead id={arrow} />
      {spec.nodes.map((label, i) => (
        <g key={i}>
          <rect x={left(i)} y={PAD} width={box} height={34} rx={4} className={marked.has(i) ? NOW : NEUTRAL} strokeWidth={1.5} />
          <text x={left(i) + box / 2} y={midY} textAnchor="middle" dominantBaseline="central" fontSize={13} className={marked.has(i) ? "fill-white" : "fill-ink"}>
            {label.length > 7 ? `${label.slice(0, 6)}…` : label}
          </text>
          {i < spec.nodes.length - 1 ? (
            <>
              <line x1={left(i) + box} y1={midY - (spec.doubly ? 4 : 0)} x2={left(i + 1) - 2} y2={midY - (spec.doubly ? 4 : 0)} className="stroke-muted" strokeWidth={1.5} markerEnd={`url(#${arrow})`} />
              {spec.doubly ? (
                <line x1={left(i + 1)} y1={midY + 5} x2={left(i) + box + 2} y2={midY + 5} className="stroke-muted" strokeWidth={1.5} markerEnd={`url(#${arrow})`} />
              ) : null}
            </>
          ) : null}
        </g>
      ))}
      {spec.circular ? (
        <path
          d={`M ${left(spec.nodes.length - 1) + box / 2} ${PAD + 34} C ${left(spec.nodes.length - 1) + box / 2} ${PAD + 78}, ${left(0) + box / 2} ${PAD + 78}, ${left(0) + box / 2} ${PAD + 36}`}
          fill="none"
          className="stroke-muted"
          strokeWidth={1.5}
          markerEnd={`url(#${arrow})`}
        />
      ) : (
        <text x={left(spec.nodes.length - 1) + box + 8} y={midY} dominantBaseline="central" fontSize={12} className="fill-muted">
          ∅
        </text>
      )}
    </svg>
  );
}

function GraphDrawing({ spec, step }: { spec: GraphSpec; step: number | null }) {
  const arrow = useId().replace(/:/g, "");
  const count = spec.nodes.length;
  const radius = Math.max(70, count * 17);
  const size = radius * 2 + 90;
  const centre = size / 2;
  const nodeR = (label: string) => Math.max(18, Math.min(34, 8 + label.length * 3.6));
  const positions = new Map(
    spec.nodes.map((n, i) => {
      const angle = (2 * Math.PI * i) / count - Math.PI / 2;
      return [n.id, { x: centre + radius * Math.cos(angle), y: centre + radius * Math.sin(angle), r: nodeR(n.label) }] as const;
    }),
  );
  const state = step !== null ? spec.steps[step] : undefined;
  const visited = new Set(state?.visited ?? []);
  const frontier = new Set(state?.frontier ?? []);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} role="img" aria-label={spec.title} className="mx-auto h-auto max-w-full">
      <Arrowhead id={arrow} />
      {spec.edges.map((edge, i) => {
        const a = positions.get(edge.from);
        const b = positions.get(edge.to);
        if (!a || !b) return null;
        if (edge.from === edge.to) {
          return <circle key={`e${i}`} cx={a.x} cy={a.y - a.r - 6} r={9} fill="none" className="stroke-muted" strokeWidth={1.5} />;
        }
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const length = Math.hypot(dx, dy) || 1;
        const x1 = a.x + (dx / length) * a.r;
        const y1 = a.y + (dy / length) * a.r;
        const x2 = b.x - (dx / length) * (b.r + (spec.directed ? 3 : 0));
        const y2 = b.y - (dy / length) * (b.r + (spec.directed ? 3 : 0));
        return (
          <g key={`e${i}`}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} className="stroke-muted" strokeWidth={1.5} markerEnd={spec.directed ? `url(#${arrow})` : undefined} />
            {edge.weight ? (
              <text x={(x1 + x2) / 2 + (dy / length) * 9} y={(y1 + y2) / 2 - (dx / length) * 9} textAnchor="middle" dominantBaseline="central" fontSize={11} className="fill-brand">
                {edge.weight}
              </text>
            ) : null}
          </g>
        );
      })}
      {spec.nodes.map((n) => {
        const p = positions.get(n.id);
        if (!p) return null;
        const now = state?.current === n.id;
        const tone = now ? NOW : visited.has(n.id) ? MARKED : frontier.has(n.id) ? WARM : NEUTRAL;
        return (
          <g key={n.id}>
            <circle cx={p.x} cy={p.y} r={p.r} className={tone} strokeWidth={1.5} />
            <text x={p.x} y={p.y} textAnchor="middle" dominantBaseline="central" fontSize={12} className={now ? "fill-white" : "fill-ink"}>
              {n.label.length > 8 ? `${n.label.slice(0, 7)}…` : n.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function ArrayDrawing({ spec, step }: { spec: ArraySpec; step: number | null }) {
  const cell = 46;
  const state = step !== null ? spec.steps[step] : undefined;
  const values = state?.values ?? spec.values;
  const highlight = new Set(state?.highlight ?? []);
  const swapped = new Set(state?.swapped ?? []);
  const sorted = new Set(state?.sorted ?? []);
  const pointersAt = new Map<number, string[]>();
  for (const [name, at] of Object.entries(state?.pointers ?? {})) pointersAt.set(at, [...(pointersAt.get(at) ?? []), name]);
  const width = PAD * 2 + values.length * cell;
  const height = PAD * 2 + 38 + (pointersAt.size > 0 ? 34 : 14) + 16;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} role="img" aria-label={spec.title} className="mx-auto h-auto max-w-full">
      {values.map((value, i) => {
        const x = PAD + i * cell;
        const tone = swapped.has(i) ? WARM : highlight.has(i) ? MARKED : sorted.has(i) ? DONE : NEUTRAL;
        return (
          <g key={i}>
            <rect x={x} y={PAD} width={cell} height={38} className={tone} strokeWidth={1.5} />
            <text x={x + cell / 2} y={PAD + 19} textAnchor="middle" dominantBaseline="central" fontSize={14} className="fill-ink">
              {value.length > 5 ? `${value.slice(0, 4)}…` : value}
            </text>
            <text x={x + cell / 2} y={PAD + 54} textAnchor="middle" fontSize={10} className="fill-faint">
              {i}
            </text>
            {pointersAt.has(i) ? (
              <text x={x + cell / 2} y={PAD + 70} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-brand">
                ↑ {(pointersAt.get(i) ?? []).join(",")}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

/** A tree, linked list, graph or array drawn from a checked JSON block, with optional steps the
 *  student moves through one at a time. Shows the text as it is when the block cannot be drawn. */
export function DiagramBlock({ code, streaming }: { code: string; streaming: boolean }) {
  const t = useT();
  const spec = useMemo(() => parseDiagram(code), [code]);
  const total = spec?.steps.length ?? 0;
  const [step, setStep] = useState(0);
  useEffect(() => setStep(0), [code]);

  if (!spec) {
    // A block still being written is not valid JSON yet.
    return streaming ? (
      <p className="my-2 text-sm text-muted" role="status">
        {t("chx.diagram.drawing")}
      </p>
    ) : (
      <pre className="my-2 overflow-x-auto rounded-xl border border-border bg-surface-2/70 p-3 text-xs">{code}</pre>
    );
  }

  const current = total > 0 ? Math.min(step, total - 1) : null;
  const note = current !== null ? spec.steps[current]?.note : "";
  return (
    <figure className="glass-flat my-3 rounded-2xl p-3.5">
      {spec.title ? <figcaption className="mb-2 text-[13px] font-medium">{spec.title}</figcaption> : null}
      <div className="overflow-x-auto">
        {spec.type === "binary_tree" ? <TreeDrawing spec={spec} step={current} /> : null}
        {spec.type === "linked_list" ? <ListDrawing spec={spec} step={current} /> : null}
        {spec.type === "graph" ? <GraphDrawing spec={spec} step={current} /> : null}
        {spec.type === "array" ? <ArrayDrawing spec={spec} step={current} /> : null}
      </div>
      {total > 0 && current !== null ? (
        <div className="mt-2 border-t border-border pt-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={current === 0}
              aria-label={t("chx.diagram.prev")}
              className="rounded border border-border p-1 text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
            </button>
            <span className="tabular text-xs text-muted">{t("chx.diagram.step", { n: current + 1, total })}</span>
            <button
              type="button"
              onClick={() => setStep((s) => Math.min(total - 1, s + 1))}
              disabled={current >= total - 1}
              aria-label={t("chx.diagram.next")}
              className="rounded border border-border p-1 text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-40"
            >
              <ChevronRight className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
          <p className={clsx("mt-1.5 min-h-[1.25rem] text-[13px]", !note && "text-faint")} aria-live="polite">
            {note || " "}
          </p>
        </div>
      ) : null}
    </figure>
  );
}
