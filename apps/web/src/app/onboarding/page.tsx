import { redirect } from "next/navigation";

import { Brand } from "@/components/brand";
import { ThemeToggle } from "@/components/kit/theme-toggle";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Reveal } from "@/components/motion/reveal";
import { OnboardingWizard } from "@/components/onboarding-wizard";
import { getT } from "@/i18n/server";
import { fetchMe } from "@/lib/api-server";

export default async function OnboardingPage() {
  const user = await fetchMe();
  if (!user) redirect("/login?next=/onboarding");
  if (user.onboarding_completed) redirect("/dashboard");
  const { t } = await getT();

  return (
    <div className="min-h-screen">
      <header className="px-3 pt-3 sm:px-6">
        <div className="glass mx-auto flex h-14 max-w-4xl items-center justify-between gap-3 rounded-2xl px-4">
          <Brand href="/onboarding" />
          <div className="flex items-center gap-3">
            <ThemeToggle className="hidden sm:flex" />
            <LocaleSwitcher persist />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 pb-16 pt-10 sm:px-6">
        <Reveal>
          <h1 className="font-display mb-8 text-balance text-3xl sm:text-4xl">
            <span className="bg-gradient-to-br from-ink via-ink to-brand bg-clip-text text-transparent">{t("onboarding.title")}</span>
          </h1>
        </Reveal>
        <OnboardingWizard user={user} />
      </main>
    </div>
  );
}
