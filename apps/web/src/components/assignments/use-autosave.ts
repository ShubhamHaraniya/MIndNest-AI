"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type SaveStatus = "saved" | "dirty" | "saving" | "error";

const DELAY_MS = 1500;

/** Keeps a draft typed on the page and saves it a moment after the student stops typing, when
 *  the field loses focus, or on demand. Saves never overlap: a change made while one is in flight
 *  is saved right after it. The text on the page is never replaced by what the server returns, so
 *  nothing typed is lost to a slow save. */
export function useDraftAutosave({
  initial,
  save,
}: {
  initial: string;
  /** Sends the text to the server; resolves to true when it was kept. */
  save: (text: string) => Promise<boolean>;
}) {
  const [draft, setDraftState] = useState(initial);
  const [status, setStatus] = useState<SaveStatus>("saved");
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const kept = useRef(initial); // what the server has
  const latest = useRef(initial); // what is on the page
  const inFlight = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveRef = useRef(save);
  saveRef.current = save;

  const flush = useCallback(async (): Promise<boolean> => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (inFlight.current) return false;
    if (latest.current === kept.current) {
      setStatus("saved");
      return true;
    }
    inFlight.current = true;
    setStatus("saving");
    const sending = latest.current;
    let ok = false;
    try {
      ok = await saveRef.current(sending);
    } finally {
      inFlight.current = false;
    }
    if (ok) {
      kept.current = sending;
      setSavedAt(new Date());
    }
    if (latest.current !== kept.current) {
      // Typed more while saving.
      if (ok) {
        setStatus("dirty");
        timer.current = setTimeout(() => void flush(), DELAY_MS);
      } else setStatus("error");
    } else setStatus(ok ? "saved" : "error");
    return ok;
  }, []);

  const setDraft = useCallback(
    (text: string) => {
      latest.current = text;
      setDraftState(text);
      setStatus((current) => (current === "saving" ? current : "dirty"));
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), DELAY_MS);
    },
    [flush],
  );

  /** Replace the text without saving it (the server already has it: a restore). */
  const reset = useCallback((text: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    kept.current = text;
    latest.current = text;
    setDraftState(text);
    setStatus("saved");
    setSavedAt(new Date());
  }, []);

  /** Wait for any save in flight, then save what is on the page. True when nothing is unsaved. */
  const saveNow = useCallback(async (): Promise<boolean> => {
    for (let attempt = 0; attempt < 20 && inFlight.current; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    const ok = await flush();
    return ok || latest.current === kept.current;
  }, [flush]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  // Leaving with unsaved text asks first.
  const unsaved = status !== "saved";
  useEffect(() => {
    if (!unsaved) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);

  return { draft, setDraft, status, savedAt, saveNow, reset };
}
