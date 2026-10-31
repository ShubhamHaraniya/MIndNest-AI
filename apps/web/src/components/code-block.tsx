"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { useT } from "@/i18n/client";

/** A fenced code block with its language and a copy button. */
export function CodeBlock({ language, code }: { language: string | null; code: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard access can be refused; nothing else to do.
    }
  }

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-border bg-surface-2/70">
      <div className="flex h-7 items-center justify-between border-b border-border px-2.5 text-[11px] text-muted">
        <span className="font-mono">{language ?? "text"}</span>
        <button
          type="button"
          onClick={() => void copy()}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-surface-3 hover:text-ink"
        >
          {copied ? <Check className="h-3 w-3" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
          {copied ? t("chat.copied") : t("chat.copy")}
        </button>
      </div>
      <pre className="!m-0 overflow-x-auto !rounded-none !border-0 !bg-transparent">
        <code>{code}</code>
      </pre>
    </div>
  );
}
