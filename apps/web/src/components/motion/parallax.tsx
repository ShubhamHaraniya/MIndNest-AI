"use client";

import { motion, useScroll, useSpring, useTransform } from "motion/react";
import { useRef, type ReactNode } from "react";

/** Moves its children vertically a little less (or more) than the page scrolls, for depth.
 *  `speed` 0.1 drifts about 60px each way over a full pass; negative reverses. */
export function Parallax({ children, speed = 0.12, className }: { children: ReactNode; speed?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const raw = useTransform(scrollYProgress, [0, 1], [speed * 600, -speed * 600]);
  const y = useSpring(raw, { stiffness: 90, damping: 24, mass: 0.6 });
  return (
    <div ref={ref} className={className}>
      <motion.div style={{ y }}>{children}</motion.div>
    </div>
  );
}
