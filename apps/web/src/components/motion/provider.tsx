"use client";

import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";

/** Every animation in the app goes through this: with "user", a visitor whose system asks for
 *  reduced motion gets instant state changes instead of movement (opacity still fades). */
export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user" transition={{ type: "spring", stiffness: 260, damping: 28, mass: 0.9 }}>
      {children}
    </MotionConfig>
  );
}
