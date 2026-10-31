"use client";

import { motion, type HTMLMotionProps } from "motion/react";
import type { ReactNode } from "react";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

/** Fades and lifts its children into view the first time they scroll on screen. */
export function Reveal({
  children,
  delay = 0,
  y = 18,
  className,
  as = "div",
  ...rest
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
  as?: "div" | "section" | "li" | "article" | "header" | "ul" | "ol";
} & Omit<HTMLMotionProps<"div">, "children" | "className">) {
  const Tag = motion[as] as unknown as typeof motion.div;
  return (
    <Tag
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "0px 0px -8% 0px" }}
      transition={{ duration: 0.6, ease: EASE, delay }}
      className={className}
      {...rest}
    >
      {children}
    </Tag>
  );
}

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.04 } },
};
const item = {
  hidden: { opacity: 0, y: 16, scale: 0.985 },
  show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.5, ease: EASE } },
};

/** A group whose `StaggerItem` children enter one after another. */
export function Stagger({
  children,
  className,
  as = "div",
  inView = true,
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "ul" | "ol" | "section";
  /** Wait until scrolled into view (default) or play on mount. */
  inView?: boolean;
}) {
  const Tag = motion[as] as unknown as typeof motion.div;
  return (
    <Tag
      variants={container}
      initial="hidden"
      {...(inView ? { whileInView: "show", viewport: { once: true, margin: "0px 0px -6% 0px" } } : { animate: "show" })}
      className={className}
    >
      {children}
    </Tag>
  );
}

export function StaggerItem({
  children,
  className,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "li" | "article" | "section";
}) {
  const Tag = motion[as] as unknown as typeof motion.div;
  return (
    <Tag variants={item} className={className}>
      {children}
    </Tag>
  );
}
