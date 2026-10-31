"use client";

import clsx from "clsx";
import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { useT } from "@/i18n/client";
import { applyTheme, isTheme, THEME_COOKIE, type Theme } from "@/lib/theme";

function readTheme(): Theme {
  const match = document.cookie.match(new RegExp(`(?:^|; )${THEME_COOKIE}=([^;]*)`));
  return isTheme(match?.[1]) ? match[1] : "dark";
}

/** Light / dark / follow the device. Three buttons so the current choice is always visible. */
export function ThemeToggle({ className }: { className?: string }) {
  const t = useT();
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => setTheme(readTheme()), []);

  const options: { id: Theme; icon: typeof Sun; label: string }[] = [
    { id: "light", icon: Sun, label: t("theme.light") },
    { id: "system", icon: Monitor, label: t("theme.system") },
    { id: "dark", icon: Moon, label: t("theme.dark") },
  ];

  return (
    <div role="radiogroup" aria-label={t("theme.label")} className={clsx("flex gap-0.5 rounded bg-surface-3 p-0.5", className)}>
      {options.map(({ id, icon: Icon, label }) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={theme === id}
          aria-label={label}
          title={label}
          onClick={() => {
            setTheme(id);
            applyTheme(id);
          }}
          className={clsx(
            "flex h-7 flex-1 items-center justify-center rounded-sm transition-colors",
            theme === id ? "bg-primary-soft text-brand" : "text-muted hover:text-ink",
          )}
        >
          <Icon className="h-4 w-4" aria-hidden />
        </button>
      ))}
    </div>
  );
}
