/** A small line-and-word diff for comparing two versions of a draft. Lines are compared first;
 *  where a block of lines was replaced, its lines are paired up and compared word by word so the
 *  reader sees which words changed, not just that a paragraph did. */

export type Segment = { text: string; changed: boolean };
export type DiffRow =
  | { kind: "same"; text: string }
  | { kind: "add" | "del"; segments: Segment[] }
  | { kind: "gap"; count: number };

export type DiffResult = { rows: DiffRow[]; added: number; removed: number; changed: boolean };

type Op = { type: "same" | "add" | "del"; text: string };

const MAX_CELLS = 4_000_000;
const CONTEXT = 2;

/** Longest-common-subsequence edit script between two token lists. */
function lcsOps(a: string[], b: string[]): Op[] {
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }
  const head: Op[] = a.slice(0, start).map((text) => ({ type: "same", text }));
  const tail: Op[] = a.slice(endA).map((text) => ({ type: "same", text }));
  const midA = a.slice(start, endA);
  const midB = b.slice(start, endB);
  const n = midA.length;
  const m = midB.length;
  if (n === 0 || m === 0 || n * m > MAX_CELLS) {
    // Too big to align exactly: show the whole middle as replaced.
    return [
      ...head,
      ...midA.map((text): Op => ({ type: "del", text })),
      ...midB.map((text): Op => ({ type: "add", text })),
      ...tail,
    ];
  }
  const width = m + 1;
  const table = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      table[i * width + j] =
        midA[i] === midB[j]
          ? table[(i + 1) * width + j + 1] + 1
          : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
  }
  const middle: Op[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (midA[i] === midB[j]) {
      middle.push({ type: "same", text: midA[i] });
      i++;
      j++;
    } else if (table[(i + 1) * width + j] >= table[i * width + j + 1]) {
      middle.push({ type: "del", text: midA[i++] });
    } else {
      middle.push({ type: "add", text: midB[j++] });
    }
  }
  while (i < n) middle.push({ type: "del", text: midA[i++] });
  while (j < m) middle.push({ type: "add", text: midB[j++] });
  return [...head, ...middle, ...tail];
}

const WORD_LIMIT = 600;

/** Word-level segments for a replaced line pair: [old line segments, new line segments]. */
function pairSegments(oldLine: string, newLine: string): [Segment[], Segment[]] {
  const a = oldLine.split(/(\s+)/).filter((part) => part !== "");
  const b = newLine.split(/(\s+)/).filter((part) => part !== "");
  if (a.length > WORD_LIMIT || b.length > WORD_LIMIT) {
    return [[{ text: oldLine, changed: true }], [{ text: newLine, changed: true }]];
  }
  const oldSegments: Segment[] = [];
  const newSegments: Segment[] = [];
  const push = (list: Segment[], text: string, changed: boolean) => {
    const last = list[list.length - 1];
    if (last && last.changed === changed) last.text += text;
    else list.push({ text, changed });
  };
  for (const op of lcsOps(a, b)) {
    if (op.type === "same") {
      push(oldSegments, op.text, false);
      push(newSegments, op.text, false);
    } else if (op.type === "del") push(oldSegments, op.text, !/^\s+$/.test(op.text));
    else push(newSegments, op.text, !/^\s+$/.test(op.text));
  }
  return [oldSegments, newSegments];
}

export function wordsIn(text: string): number {
  const trimmed = text.trim();
  return trimmed === "" ? 0 : trimmed.split(/\s+/).length;
}

function changedWords(segments: Segment[]): number {
  return segments.filter((segment) => segment.changed).reduce((sum, segment) => sum + wordsIn(segment.text), 0);
}

/** Compare two texts. Unchanged stretches longer than a few lines collapse to a "gap" row. */
export function diffTexts(before: string, after: string): DiffResult {
  const ops = lcsOps(before.split("\n"), after.split("\n"));
  const rows: DiffRow[] = [];
  let added = 0;
  let removed = 0;
  for (let index = 0; index < ops.length; ) {
    if (ops[index].type === "same") {
      rows.push({ kind: "same", text: ops[index].text });
      index++;
      continue;
    }
    const dels: string[] = [];
    const adds: string[] = [];
    while (index < ops.length && ops[index].type !== "same") {
      (ops[index].type === "del" ? dels : adds).push(ops[index].text);
      index++;
    }
    const pairs = Math.min(dels.length, adds.length);
    const delRows: DiffRow[] = [];
    const addRows: DiffRow[] = [];
    for (let k = 0; k < dels.length; k++) {
      if (k < pairs) {
        const [oldSegments, newSegments] = pairSegments(dels[k], adds[k]);
        delRows.push({ kind: "del", segments: oldSegments });
        addRows.push({ kind: "add", segments: newSegments });
        removed += changedWords(oldSegments);
        added += changedWords(newSegments);
      } else {
        delRows.push({ kind: "del", segments: [{ text: dels[k], changed: true }] });
        removed += wordsIn(dels[k]);
      }
    }
    for (let k = pairs; k < adds.length; k++) {
      addRows.push({ kind: "add", segments: [{ text: adds[k], changed: true }] });
      added += wordsIn(adds[k]);
    }
    rows.push(...delRows, ...addRows);
  }
  return { rows: collapse(rows), added, removed, changed: added + removed > 0 || before !== after };
}

/** Keep CONTEXT unchanged lines around each change and fold the rest. */
function collapse(rows: DiffRow[]): DiffRow[] {
  const keep = new Array<boolean>(rows.length).fill(false);
  rows.forEach((row, index) => {
    if (row.kind === "same") return;
    for (let k = Math.max(0, index - CONTEXT); k <= Math.min(rows.length - 1, index + CONTEXT); k++) keep[k] = true;
  });
  if (!keep.some(Boolean)) return rows.length > 0 ? [{ kind: "gap", count: rows.length }] : [];
  const out: DiffRow[] = [];
  let hidden = 0;
  rows.forEach((row, index) => {
    if (keep[index]) {
      if (hidden > 0) out.push({ kind: "gap", count: hidden });
      hidden = 0;
      out.push(row);
    } else hidden++;
  });
  if (hidden > 0) out.push({ kind: "gap", count: hidden });
  return out;
}
