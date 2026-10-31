"use client";

import { Children, isValidElement, useMemo, useRef, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import "katex/dist/katex.min.css";

import { CodeBlock } from "@/components/code-block";
import { DiagramBlock } from "@/components/chat/diagram";
import { MermaidDiagram } from "@/components/mermaid-diagram";

/** Turn `[2]` into a link the renderer shows as a citation chip. Code is left alone, and only
 *  numbers that match a real source become chips, so a stray "[9]" stays plain text. */
export function linkCitations(text: string, valid: Set<number>): string {
  if (valid.size === 0) return text;
  return text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part.replace(/\[(\d{1,2})\](?!\()/g, (match, digits: string) =>
            valid.has(Number(digits)) ? `[${digits}](#cite-${digits})` : match,
          ),
    )
    .join("");
}

const DRAWN = /(^|\s)language-(mermaid|mindnest-diagram)(\s|$)/;

/** Mermaid and the tutor's own diagrams draw themselves; everything else is a code block. */
function isDrawn(child: ReactNode): boolean {
  if (!isValidElement(child)) return false;
  return DRAWN.test((child.props as { className?: string }).className ?? "");
}

export function Markdown({
  text,
  citations,
  streaming,
  onCite,
}: {
  text: string;
  citations: number[];
  streaming: boolean;
  onCite: (n: number) => void;
}) {
  // The callback may change identity between renders; keeping it in a ref keeps the renderer's
  // component types stable, so diagrams are not torn down and redrawn.
  const cite = useRef(onCite);
  cite.current = onCite;
  const source = useMemo(() => linkCitations(text, new Set(citations)), [text, citations]);

  const components: Components = useMemo(
    () => ({
      a({ href, children }) {
        if (href?.startsWith("#cite-")) {
          const n = Number(href.slice(6));
          return (
            <button
              type="button"
              onClick={() => cite.current(n)}
              aria-label={`[${n}]`}
              className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-md border border-border bg-surface-2/70 px-1 align-baseline text-[11px] font-semibold leading-none text-brand hover:border-primary hover:bg-primary hover:text-on-primary"
            >
              {n}
            </button>
          );
        }
        const safe = href && /^https?:\/\//i.test(href);
        return safe ? (
          <a href={href} target="_blank" rel="noopener noreferrer nofollow">
            {children}
          </a>
        ) : (
          <span>{children}</span>
        );
      },
      // Images are never loaded: a link to an outside picture is a way to send data out.
      img({ alt }) {
        return alt ? <span className="text-muted">[{alt}]</span> : null;
      },
      pre({ children }) {
        const first = Children.toArray(children)[0];
        if (isDrawn(first)) return <>{children}</>;
        if (isValidElement(first)) {
          const props = first.props as { className?: string; children?: ReactNode };
          const language = /language-([\w+-]+)/.exec(props.className ?? "")?.[1] ?? null;
          return <CodeBlock language={language} code={String(props.children ?? "").replace(/\n$/, "")} />;
        }
        return <pre>{children}</pre>;
      },
      table({ children }) {
        return (
          <div className="table-wrap">
            <table>{children}</table>
          </div>
        );
      },
      code({ className, children }) {
        if (/(^|\s)language-mermaid(\s|$)/.test(className ?? "")) {
          return <MermaidDiagram code={String(children).replace(/\n$/, "")} streaming={streaming} />;
        }
        if (/(^|\s)language-mindnest-diagram(\s|$)/.test(className ?? "")) {
          return <DiagramBlock code={String(children).replace(/\n$/, "")} streaming={streaming} />;
        }
        return <code className={className}>{children}</code>;
      },
    }),
    [streaming],
  );

  return (
    <div className="md-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: true }]]}
        rehypePlugins={[[rehypeKatex, { strict: "ignore", throwOnError: false, trust: false, output: "htmlAndMathml" }]]}
        components={components}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
