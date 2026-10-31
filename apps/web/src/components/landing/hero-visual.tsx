"use client";

import { BookOpen, FileText, Sparkles } from "lucide-react";
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import type { PointerEvent } from "react";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

/** The hero's showpiece: a labelled sample conversation drawn as three layers of glass that tilt a few
 *  degrees toward the pointer. It is a sample, not a real answer, and says so. */
export function HeroVisual({
  label,
  question,
  answer,
  source,
  noteTitle,
  chip,
}: {
  label: string;
  question: string;
  answer: string;
  source: string;
  noteTitle: string;
  chip: string;
}) {
  const reduce = useReducedMotion();
  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const rx = useSpring(useTransform(py, [-0.5, 0.5], [5, -5]), { stiffness: 120, damping: 18 });
  const ry = useSpring(useTransform(px, [-0.5, 0.5], [-7, 7]), { stiffness: 120, damping: 18 });
  const backX = useTransform(px, [-0.5, 0.5], [14, -14]);
  const backY = useTransform(py, [-0.5, 0.5], [10, -10]);
  const frontX = useTransform(px, [-0.5, 0.5], [-12, 12]);
  const frontY = useTransform(py, [-0.5, 0.5], [-8, 8]);

  function onMove(event: PointerEvent<HTMLDivElement>) {
    if (reduce) return;
    const box = event.currentTarget.getBoundingClientRect();
    px.set((event.clientX - box.left) / box.width - 0.5);
    py.set((event.clientY - box.top) / box.height - 0.5);
  }
  function onLeave() {
    px.set(0);
    py.set(0);
  }

  return (
    <div className="relative mx-auto w-full max-w-[34rem] [perspective:1200px]" onPointerMove={onMove} onPointerLeave={onLeave}>
      {/* back layer: a note card */}
      <motion.div
        aria-hidden
        style={{ x: backX, y: backY }}
        initial={{ opacity: 0, scale: 0.94 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.9, ease: EASE, delay: 0.35 }}
        className="glass absolute -right-3 -top-6 hidden w-52 rounded-2xl p-4 sm:block"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <FileText className="h-4 w-4" aria-hidden />
        </span>
        <p className="mt-3 text-xs font-medium text-ink">{noteTitle}</p>
        <div className="mt-2 space-y-1.5">
          <span className="block h-1.5 w-full rounded-full bg-surface-3" />
          <span className="block h-1.5 w-4/5 rounded-full bg-surface-3" />
          <span className="block h-1.5 w-3/5 rounded-full bg-surface-3" />
        </div>
      </motion.div>

      {/* middle layer: the conversation */}
      <motion.figure
        style={reduce ? undefined : { rotateX: rx, rotateY: ry, transformStyle: "preserve-3d" }}
        initial={{ opacity: 0, y: 28 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.9, ease: EASE, delay: 0.2 }}
        className="glass-strong sheen relative overflow-hidden rounded-3xl"
      >
        <figcaption className="flex items-center gap-2 border-b border-border px-5 py-3 text-xs text-muted">
          <span className="flex gap-1.5" aria-hidden>
            <span className="h-2.5 w-2.5 rounded-full bg-danger/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-warning/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-success/70" />
          </span>
          <span className="ml-1">{label}</span>
        </figcaption>
        <div className="space-y-3.5 p-5 text-sm">
          <motion.p
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.6, ease: EASE, delay: 0.7 }}
            className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-on-primary shadow-glow"
          >
            {question}
          </motion.p>
          <motion.p
            initial={{ opacity: 0, x: -16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.6, ease: EASE, delay: 1.05 }}
            className="glass-flat max-w-[92%] rounded-2xl rounded-bl-md px-4 py-3 leading-relaxed"
          >
            {answer}
          </motion.p>
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: EASE, delay: 1.4 }}
            className="inline-flex items-center gap-1.5 rounded-full bg-primary-soft px-3 py-1.5 text-xs text-brand ring-1 ring-primary/25"
          >
            <BookOpen className="h-3.5 w-3.5" aria-hidden />
            {source}
          </motion.p>
        </div>
      </motion.figure>

      {/* front layer: a small pulse chip */}
      <motion.div
        aria-hidden
        style={{ x: frontX, y: frontY }}
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.8, ease: EASE, delay: 1.2 }}
        className="glass absolute -bottom-5 -left-3 hidden items-center gap-2 rounded-full px-4 py-2 text-xs sm:flex"
      >
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
        </span>
        <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden />
        <span className="text-muted">{chip}</span>
      </motion.div>
    </div>
  );
}
