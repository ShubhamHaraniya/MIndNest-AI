"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

export type Resource<T> = {
  data: T | null;
  /** True until the first answer (or failure) arrives; later refreshes keep showing the old data. */
  loading: boolean;
  error: string | null;
  reload: () => void;
  setData: (update: (current: T) => T) => void;
};

/** GET `path` and keep the result. `reload()` refetches in the background without a loading
 *  flash, so lists that poll (files being read) do not blink. Pass null to stay idle. With
 *  `keepPrevious`, changing the path (a new search) keeps showing the old rows until the new ones arrive. */
export function useResource<T>(path: string | null, options: { keepPrevious?: boolean } = {}): Resource<T> {
  const t = useT();
  const [data, setDataState] = useState<T | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const loadedPath = useRef<string | null>(null);

  useEffect(() => {
    if (path === null) return;
    const controller = new AbortController();
    if (loadedPath.current !== path) {
      loadedPath.current = path;
      if (!options.keepPrevious) {
        setDataState(null);
        setLoading(true);
      }
    }
    api<T>(path, { signal: controller.signal })
      .then((value) => {
        setDataState(value);
        setError(null);
        setLoading(false);
      })
      .catch((caught) => {
        if (controller.signal.aborted) return;
        setError(errorMessage(caught, t));
        setLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, version, t]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const setData = useCallback((update: (current: T) => T) => {
    setDataState((current) => (current === null ? current : update(current)));
  }, []);
  return { data, loading, error, reload, setData };
}
