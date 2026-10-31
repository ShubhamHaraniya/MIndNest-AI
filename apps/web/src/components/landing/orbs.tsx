"use client";

import { Parallax } from "@/components/motion/parallax";

/** Soft colour behind the hero that moves at its own speed as the page scrolls. Decoration only. */
export function HeroOrbs() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <Parallax speed={0.18} className="absolute -left-24 top-10 h-72 w-72">
        <div className="h-full w-full rounded-full bg-primary/20 blur-3xl" />
      </Parallax>
      <Parallax speed={-0.14} className="absolute -right-16 top-40 h-80 w-80">
        <div className="h-full w-full rounded-full bg-accent/15 blur-3xl" />
      </Parallax>
    </div>
  );
}
