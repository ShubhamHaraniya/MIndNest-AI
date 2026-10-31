"use client";

import { motion } from "motion/react";

/** Three steps along a line that draws itself, left to right, as the section scrolls into view. */
export function Steps({ steps }: { steps: { title: string; body: string }[] }) {
  return (
    <div className="relative mt-10">
      <div aria-hidden className="absolute left-[18px] right-[18px] top-[18px] hidden h-px bg-border md:block">
        <motion.span
          className="block h-full origin-left bg-gradient-to-r from-primary via-accent to-primary"
          style={{ boxShadow: "0 0 12px var(--primary)" }}
          initial={{ scaleX: 0 }}
          whileInView={{ scaleX: 1 }}
          viewport={{ once: true, margin: "0px 0px -15% 0px" }}
          transition={{ duration: 1.4, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
      <ol className="grid gap-8 md:grid-cols-3 md:gap-6">
        {steps.map((step, index) => (
          <motion.li
            key={step.title}
            className="relative"
            initial={{ opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "0px 0px -10% 0px" }}
            transition={{ duration: 0.6, delay: 0.15 + index * 0.18, ease: [0.22, 1, 0.36, 1] }}
          >
            <span
              className="font-display relative z-10 flex h-9 w-9 items-center justify-center rounded-full bg-primary text-sm text-on-primary shadow-glow ring-4 ring-bg"
              aria-hidden
            >
              {index + 1}
            </span>
            <h3 className="mt-4 text-[15px] font-semibold">{step.title}</h3>
            <p className="mt-1.5 max-w-xs text-sm text-muted">{step.body}</p>
          </motion.li>
        ))}
      </ol>
    </div>
  );
}
