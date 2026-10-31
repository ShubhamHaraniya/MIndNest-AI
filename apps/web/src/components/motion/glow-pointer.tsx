"use client";

import { useEffect } from "react";

/** One pointer listener for the whole app. It tells the card under the pointer where the pointer
 *  is, as --mx / --my, so `.spot` cards can light up around it. Nothing renders; touch is ignored. */
export function GlowPointer() {
  useEffect(() => {
    if (window.matchMedia("(pointer: coarse)").matches) return;
    let frame = 0;
    let last: PointerEvent | null = null;
    function paint() {
      frame = 0;
      const event = last;
      if (!event) return;
      const card = (event.target as Element | null)?.closest?.(".spot") as HTMLElement | null;
      if (!card) return;
      const box = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${event.clientX - box.left}px`);
      card.style.setProperty("--my", `${event.clientY - box.top}px`);
    }
    function onMove(event: PointerEvent) {
      last = event;
      if (!frame) frame = requestAnimationFrame(paint);
    }
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return null;
}
