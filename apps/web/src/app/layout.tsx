import "@fontsource-variable/inter";
import "@fontsource-variable/noto-sans-devanagari";
import "@fontsource-variable/noto-sans-gujarati";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/source-serif-4";

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { ToastProvider } from "@/components/kit/toast";
import { GlowPointer } from "@/components/motion/glow-pointer";
import { MotionProvider } from "@/components/motion/provider";
import { I18nProvider } from "@/i18n/client";
import { getLocale } from "@/i18n/server";
import { getMessages } from "@/i18n/translate";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "MindNest AI",
  description: "AI-powered learning for every student.",
};

export const viewport: Viewport = {
  themeColor: "#060a12",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  return (
    // data-theme is set by the boot script before first paint, which is why React must not
    // complain that the server markup differs from what the browser ended up with.
    <html lang={locale} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>
        <div className="aurora" aria-hidden />
        <GlowPointer />
        <I18nProvider locale={locale} messages={getMessages(locale)}>
          <MotionProvider>
            <ToastProvider>{children}</ToastProvider>
          </MotionProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
