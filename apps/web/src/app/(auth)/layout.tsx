import { Check, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import { Brand } from "@/components/brand";
import { ThemeToggle } from "@/components/kit/theme-toggle";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { PageTransition } from "@/components/motion/page-transition";
import { Stagger, StaggerItem } from "@/components/motion/reveal";
import { getT } from "@/i18n/server";

export default async function AuthLayout({ children }: { children: ReactNode }) {
  const { t } = await getT();
  const points = [t("landing.f2Title"), t("landing.f3Title"), t("landing.f4Title"), t("landing.f5Title")];
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]">
      {/* The story side: a headline over slow orbit rings, with the benefits as floating chips. */}
      <aside className="relative hidden flex-col justify-between overflow-hidden p-12 lg:flex">
        <div aria-hidden className="pointer-events-none absolute inset-0">
          <div className="absolute left-1/2 top-1/2 h-[46rem] w-[46rem] -translate-x-1/2 -translate-y-1/2 rounded-full border border-border/60" />
          <div className="absolute left-1/2 top-1/2 h-[32rem] w-[32rem] -translate-x-1/2 -translate-y-1/2 rounded-full border border-border/70" />
          <div className="absolute left-1/2 top-1/2 h-[19rem] w-[19rem] -translate-x-1/2 -translate-y-1/2 rounded-full border border-primary/25 shadow-glow" />
          <span className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 animate-glow-pulse rounded-full bg-primary shadow-glow" />
        </div>

        <Brand className="relative" />

        <Stagger inView={false} className="relative max-w-lg">
          <StaggerItem>
            <p className="font-display text-balance text-4xl leading-[1.12] xl:text-5xl">
              <span className="bg-gradient-to-br from-ink via-ink to-brand bg-clip-text text-transparent">{t("landing.heroTitle")}</span>
            </p>
          </StaggerItem>
          <StaggerItem>
            <ul className="mt-8 flex flex-wrap gap-2.5 text-sm">
              {points.map((point) => (
                <li key={point} className="glass flex items-center gap-2 rounded-full py-2 pl-2.5 pr-4">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-on-primary">
                    <Check className="h-3 w-3" strokeWidth={3} aria-hidden />
                  </span>
                  {point}
                </li>
              ))}
            </ul>
          </StaggerItem>
          <StaggerItem>
            <p className="glass mt-6 flex gap-3 rounded-2xl p-4 text-xs leading-relaxed text-muted">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
              {t("landing.privacyBody")}
            </p>
          </StaggerItem>
        </Stagger>

        <p className="relative text-xs text-faint">{t("landing.footer")}</p>
      </aside>

      <div className="flex min-w-0 flex-col">
        <div className="flex items-center justify-between gap-3 px-6 py-5">
          <Brand className="lg:invisible" />
          <div className="flex items-center gap-3">
            <ThemeToggle className="hidden sm:flex" />
            <LocaleSwitcher />
          </div>
        </div>
        <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-5 pb-16">
          <PageTransition>
            <div className="glass-strong sheen rounded-3xl p-7 sm:p-9">{children}</div>
          </PageTransition>
        </main>
      </div>
    </div>
  );
}
