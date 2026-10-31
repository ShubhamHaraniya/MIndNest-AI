import { ArrowRight, BookOpen, CalendarCheck, Check, FileText, Languages, ListChecks, MessageSquareQuote, ShieldCheck } from "lucide-react";

import { Brand } from "@/components/brand";
import { ButtonLink } from "@/components/kit/button";
import { ThemeToggle } from "@/components/kit/theme-toggle";
import { HeroOrbs } from "@/components/landing/orbs";
import { HeroVisual } from "@/components/landing/hero-visual";
import { Steps } from "@/components/landing/steps";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Reveal, Stagger, StaggerItem } from "@/components/motion/reveal";
import { getT } from "@/i18n/server";
import { fetchMe } from "@/lib/api-server";

export default async function LandingPage() {
  const { t } = await getT();
  // The public landing page must still render if the API is briefly down.
  const user = await fetchMe().catch(() => null);

  const features = [
    { icon: BookOpen, title: t("landing.f1Title"), body: t("landing.f1Body") },
    { icon: MessageSquareQuote, title: t("landing.f2Title"), body: t("landing.f2Body") },
    { icon: ListChecks, title: t("landing.f3Title"), body: t("landing.f3Body") },
    { icon: FileText, title: t("landing.f4Title"), body: t("landing.f4Body") },
    { icon: CalendarCheck, title: t("landing.f5Title"), body: t("landing.f5Body") },
    { icon: Languages, title: t("landing.f6Title"), body: t("landing.f6Body") },
  ];
  const steps = [
    { title: t("landing.step1Title"), body: t("landing.step1Body") },
    { title: t("landing.step2Title"), body: t("landing.step2Body") },
    { title: t("landing.step3Title"), body: t("landing.step3Body") },
  ];
  const trust = [t("landing.trustCite"), t("landing.trustLang"), t("landing.trustByok")];

  return (
    <div className="min-h-screen overflow-x-clip">
      {/* A floating glass bar, not a full-width strip. */}
      <header className="sticky top-0 z-30 px-3 pt-3 sm:px-6">
        <div className="glass mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 rounded-2xl px-3 sm:px-5">
          <Brand compact className="sm:hidden" />
          <Brand className="hidden sm:flex" />
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="hidden sm:block">
              <ThemeToggle />
            </div>
            <LocaleSwitcher />
            {user ? (
              <ButtonLink href="/dashboard" size="sm">
                {t("landing.openApp")}
              </ButtonLink>
            ) : (
              <>
                <ButtonLink href="/login" variant="ghost" size="sm" className="hidden sm:inline-flex">
                  {t("landing.signIn")}
                </ButtonLink>
                <ButtonLink href="/signup" size="sm">
                  {t("landing.getStarted")}
                </ButtonLink>
              </>
            )}
          </div>
        </div>
      </header>

      <main>
        {/* Hero: headline on the left, three layers of glass on the right. */}
        <section className="relative">
          <HeroOrbs />
          <div className="relative mx-auto grid max-w-6xl items-center gap-14 px-4 pb-20 pt-14 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pb-28 lg:pt-24">
            <Stagger inView={false}>
              <StaggerItem>
                <p className="glass inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs font-semibold text-brand">
                  <span className="relative flex h-2 w-2" aria-hidden>
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                  </span>
                  {t("landing.eyebrow")}
                </p>
              </StaggerItem>
              <StaggerItem>
                <h1 className="font-display mt-6 text-balance text-4xl leading-[1.06] sm:text-6xl">
                  <span className="bg-gradient-to-br from-ink via-ink to-brand bg-clip-text text-transparent">{t("landing.heroTitle")}</span>
                </h1>
              </StaggerItem>
              <StaggerItem>
                <p className="mt-5 max-w-xl text-base text-muted sm:text-lg">{t("landing.heroSubtitle")}</p>
              </StaggerItem>
              {user ? null : (
                <StaggerItem>
                  <div className="mt-8 flex flex-wrap gap-3">
                    <ButtonLink href="/signup" size="lg">
                      {t("landing.getStarted")}
                      <ArrowRight className="h-4 w-4 rtl:rotate-180" aria-hidden />
                    </ButtonLink>
                    <ButtonLink href="/login" variant="secondary" size="lg">
                      {t("landing.heroSecondary")}
                    </ButtonLink>
                  </div>
                </StaggerItem>
              )}
              <StaggerItem>
                <ul className="mt-8 flex flex-wrap gap-x-5 gap-y-2.5 text-sm text-muted">
                  {trust.map((item) => (
                    <li key={item} className="flex items-center gap-2">
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-success-soft text-success ring-1 ring-success/30">
                        <Check className="h-3 w-3" strokeWidth={3} aria-hidden />
                      </span>
                      {item}
                    </li>
                  ))}
                </ul>
              </StaggerItem>
            </Stagger>

            <HeroVisual
              label={t("landing.sampleLabel")}
              question={t("landing.sampleQuestion")}
              answer={t("landing.sampleAnswer")}
              source={t("landing.sampleSource")}
              noteTitle={t("landing.f4Title")}
              chip={trust[0]}
            />
          </div>
        </section>

        {/* Features: a bento grid, the first card wide, the rest in a staggered rhythm. */}
        <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
          <Reveal>
            <h2 className="font-display max-w-2xl text-balance text-3xl sm:text-4xl">{t("landing.featuresTitle")}</h2>
          </Reveal>
          <Stagger as="ul" className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
            {features.map(({ icon: Icon, title, body }, index) => (
              <StaggerItem
                as="li"
                key={title}
                className={
                  index === 0
                    ? "lg:col-span-4"
                    : index === 3
                      ? "lg:col-span-4"
                      : "lg:col-span-2"
                }
              >
                <div className="glass card-hover spot h-full rounded-card p-6">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-soft text-brand ring-1 ring-primary/25">
                    <Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden />
                  </span>
                  <h3 className="mt-5 text-base font-semibold">{title}</h3>
                  <p className="mt-1.5 max-w-lg text-sm text-muted">{body}</p>
                </div>
              </StaggerItem>
            ))}
          </Stagger>
        </section>

        <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
          <Reveal>
            <h2 className="font-display text-3xl sm:text-4xl">{t("landing.howTitle")}</h2>
          </Reveal>
          <Steps steps={steps} />
        </section>

        <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
          <Reveal>
            <div className="glass flex gap-5 rounded-card p-6 sm:p-8">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-success-soft text-success ring-1 ring-success/30">
                <ShieldCheck className="h-6 w-6" strokeWidth={1.75} aria-hidden />
              </span>
              <div>
                <h2 className="font-display text-xl">{t("landing.privacyTitle")}</h2>
                <p className="mt-1.5 max-w-3xl text-sm text-muted">{t("landing.privacyBody")}</p>
              </div>
            </div>
          </Reveal>
        </section>

        {user ? null : (
          <section className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
            <Reveal>
              <div className="glass-strong sheen relative overflow-hidden rounded-3xl p-8 sm:p-12">
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-0 -z-10"
                  style={{ background: "radial-gradient(40rem 18rem at 85% 0%, color-mix(in srgb, var(--primary) 22%, transparent), transparent 70%), radial-gradient(30rem 16rem at 0% 100%, color-mix(in srgb, var(--accent) 16%, transparent), transparent 70%)" }}
                />
                <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h2 className="font-display max-w-xl text-balance text-3xl sm:text-4xl">{t("landing.ctaTitle")}</h2>
                    <p className="mt-2 max-w-xl text-sm text-muted sm:text-base">{t("landing.ctaBody")}</p>
                  </div>
                  <ButtonLink href="/signup" size="lg" className="shrink-0">
                    {t("landing.getStarted")}
                    <ArrowRight className="h-4 w-4 rtl:rotate-180" aria-hidden />
                  </ButtonLink>
                </div>
              </div>
            </Reveal>
          </section>
        )}
      </main>

      <footer className="border-t border-border py-6 text-center text-xs text-muted">{t("landing.footer")}</footer>
    </div>
  );
}
