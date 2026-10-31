"use client";

import clsx from "clsx";
import { ClipboardCopy, Download, Image as ImageIcon, Maximize2, Minimize2, Minus, Plus, ScanSearch } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { useT } from "@/i18n/client";
import { repairMermaid } from "@/lib/mermaid";

const MIN_SCALE = 0.4;
const MAX_SCALE = 6;

function currentTheme(): "dark" | "light" {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

/** The page's light/dark setting, kept in sync so a diagram redraws when the student switches. */
function useThemeName(): "dark" | "light" {
  const [theme, setTheme] = useState<"dark" | "light">("light");
  useEffect(() => {
    setTheme(currentTheme());
    const observer = new MutationObserver(() => setTheme(currentTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

function svgSize(svg: string): { width: number; height: number } {
  const box = /viewBox="([\d.\-\s]+)"/.exec(svg)?.[1]?.trim().split(/\s+/).map(Number);
  if (box && box.length === 4 && box[2] > 0 && box[3] > 0) return { width: box[2], height: box[3] };
  return { width: 800, height: 600 };
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Draws a Mermaid diagram written by the AI, inside a small viewer: zoom, drag to pan, full
 *  screen, copy the source, and download as SVG or PNG.
 *
 *  Mermaid runs in "strict" mode, which sanitises the drawing, and the library is loaded only
 *  when the first diagram appears. While the answer is still streaming the code is incomplete,
 *  so it is shown as plain text and drawn once the answer is finished. */
export function MermaidDiagram({ code, streaming }: { code: string; streaming: boolean }) {
  const t = useT();
  const theme = useThemeName();
  const id = `mmd-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  useEffect(() => {
    if (streaming) return;
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: theme === "dark" ? "dark" : "neutral",
          suppressErrorRendering: true,
          // Labels as SVG text (not HTML) so the picture can also be exported as a PNG.
          htmlLabels: false,
          flowchart: { htmlLabels: false },
        });
        // Draw it as written; if Mermaid refuses, try once more with unquoted labels fixed.
        let source = code;
        try {
          await mermaid.parse(source);
        } catch (first) {
          const repaired = repairMermaid(code);
          if (repaired === code) throw first;
          await mermaid.parse(repaired);
          source = repaired;
        }
        const result = await mermaid.render(id, source);
        if (!cancelled) {
          setSvg(result.svg);
          setFailed(false);
          setView({ scale: 1, x: 0, y: 0 });
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, streaming, id, theme]);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [expanded]);

  const zoom = useCallback((factor: number) => {
    setView((v) => ({ ...v, scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.scale * factor)) }));
  }, []);

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, ox: view.x, oy: view.y };
  }
  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const start = drag.current;
    if (!start) return;
    setView((v) => ({ ...v, x: start.ox + event.clientX - start.x, y: start.oy + event.clientY - start.y }));
  }
  function onPointerUp() {
    drag.current = null;
  }

  async function copySource() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard access can be refused; nothing else to do.
    }
  }

  function downloadSvg() {
    if (svg) save(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }), "diagram.svg");
  }

  function downloadPng() {
    if (!svg) return;
    const { width, height } = svgSize(svg);
    const scale = 2;
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      const context = canvas.getContext("2d");
      if (!context) return;
      context.fillStyle = theme === "dark" ? "#0c1320" : "#f8fbfb";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        if (blob) save(blob, "diagram.png");
      }, "image/png");
    };
    const sized = svg.replace(/<svg /, `<svg width="${width}" height="${height}" `);
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(sized)}`;
  }

  if (streaming || (!svg && !failed)) {
    return (
      <pre className="my-3 overflow-x-auto text-xs text-muted">
        <code>{code}</code>
      </pre>
    );
  }

  if (failed || !svg) {
    return (
      <div className="my-3">
        <p className="mb-1 text-xs text-muted">{t("chat.diagramFailed")}</p>
        <pre className="overflow-x-auto text-xs">
          <code>{code}</code>
        </pre>
      </div>
    );
  }

  const tool =
    "flex h-7 w-7 items-center justify-center rounded text-muted hover:bg-surface-3 hover:text-ink focus-visible:outline-none";

  return (
    <figure
      className={clsx(
        "border border-border bg-surface",
        expanded ? "fixed inset-3 z-50 flex flex-col shadow-pop" : "my-3 rounded",
      )}
    >
      <figcaption className="flex items-center justify-between gap-2 border-b border-border px-2 py-1">
        <span className="px-1 text-[11px] font-medium text-muted" title={t("diagram.hint")}>
          {t("diagram.label")}
        </span>
        <div className="flex items-center">
          <button type="button" className={tool} onClick={() => zoom(0.8)} aria-label={t("diagram.zoomOut")} title={t("diagram.zoomOut")}>
            <Minus className="h-3.5 w-3.5" aria-hidden />
          </button>
          <span className="tabular w-10 text-center text-[11px] text-muted" aria-live="polite">
            {Math.round(view.scale * 100)}%
          </span>
          <button type="button" className={tool} onClick={() => zoom(1.25)} aria-label={t("diagram.zoomIn")} title={t("diagram.zoomIn")}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button type="button" className={tool} onClick={() => setView({ scale: 1, x: 0, y: 0 })} aria-label={t("diagram.reset")} title={t("diagram.reset")}>
            <ScanSearch className="h-3.5 w-3.5" aria-hidden />
          </button>
          <span className="mx-1 h-4 w-px bg-border" aria-hidden />
          <button type="button" className={tool} onClick={() => void copySource()} aria-label={t("diagram.copySource")} title={copied ? t("chat.copied") : t("diagram.copySource")}>
            <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button type="button" className={tool} onClick={downloadSvg} aria-label={t("diagram.downloadSvg")} title={t("diagram.downloadSvg")}>
            <Download className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button type="button" className={tool} onClick={downloadPng} aria-label={t("diagram.downloadPng")} title={t("diagram.downloadPng")}>
            <ImageIcon className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button
            type="button"
            className={tool}
            onClick={() => setExpanded((value) => !value)}
            aria-label={expanded ? t("diagram.collapse") : t("diagram.expand")}
            title={expanded ? t("diagram.collapse") : t("diagram.expand")}
          >
            {expanded ? <Minimize2 className="h-3.5 w-3.5" aria-hidden /> : <Maximize2 className="h-3.5 w-3.5" aria-hidden />}
          </button>
        </div>
      </figcaption>
      <div
        role="img"
        aria-label={t("diagram.label")}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={(event) => {
          if (event.ctrlKey || event.metaKey) zoom(event.deltaY < 0 ? 1.1 : 0.9);
        }}
        className={clsx(
          "touch-none cursor-grab select-none overflow-hidden active:cursor-grabbing",
          expanded ? "min-h-0 flex-1" : "max-h-[min(26rem,60vh)]",
        )}
      >
        <div
          className={clsx(
            "flex w-full items-center justify-center p-3 [&_svg]:h-auto [&_svg]:max-w-full",
            expanded ? "h-full [&_svg]:max-h-full" : "[&_svg]:max-h-[min(24rem,56vh)]",
          )}
          style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`, transformOrigin: "center" }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
      <details className="border-t border-border px-3 py-1.5 text-xs text-muted">
        <summary className="cursor-pointer">{t("chat.viewSource")}</summary>
        <pre className="mt-1.5 overflow-x-auto">
          <code>{code}</code>
        </pre>
      </details>
    </figure>
  );
}
