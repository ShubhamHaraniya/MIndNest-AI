/** Small repairs for Mermaid written by an AI.
 *
 *  The most common mistake is an unquoted label that contains brackets, for example
 *  `A[Reason (think)] --> B[Act]`. Mermaid reads the "(" as the start of a new shape and refuses to
 *  draw the whole diagram. Wrapping the label in double quotes fixes it. This runs only after the
 *  diagram failed to parse as written, and only on flowcharts, so a diagram that already works is
 *  never touched. */

const FLOWCHART = /^\s*(?:%%.*\n\s*)*(?:flowchart|graph)\b/i;

function quote(label: string): string {
  return `"${label.replace(/"/g, "#quot;")}"`;
}

function needsQuotes(label: string): boolean {
  const text = label.trim();
  if (!text) return false;
  // Already quoted, or special shape syntax such as [(database)], [/slanted/], [\slanted\].
  if (text.startsWith('"') || /^[(/\\]/.test(text)) return false;
  return /[(){}<>&;:,'#]|\//.test(text);
}

export function repairMermaid(code: string): string {
  if (!FLOWCHART.test(code)) return code;
  return (
    code
      // Node labels in square brackets: A[text]
      .replace(/(\b[A-Za-z_][\w-]*)\[([^[\]"\n]*)\]/g, (whole, id: string, label: string) =>
        needsQuotes(label) ? `${id}[${quote(label.trim())}]` : whole,
      )
      // Decision nodes in braces: D{text}  (not the hexagon form D{{text}})
      .replace(/(\b[A-Za-z_][\w-]*)\{([^{}"\n]*)\}/g, (whole, id: string, label: string) =>
        needsQuotes(label) ? `${id}{${quote(label.trim())}}` : whole,
      )
      // Edge labels: -->|text|
      .replace(/\|([^|"\n]+)\|/g, (whole, label: string) =>
        needsQuotes(label) ? `|${quote(label.trim())}|` : whole,
      )
  );
}
