"use client";

import { useCallback, useEffect, useState } from "react";
import { m } from "@/messages";

type State<T> = { data: T | undefined; error: string | null; loading: boolean };

/** Run an async loader when `deps` change; loaders throw an Error with the message to show. */
export function useLoad<T>(
  load: () => Promise<T>,
  deps: readonly unknown[],
): State<T> & { reload: () => void } {
  const [state, setState] = useState<State<T>>({ data: undefined, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    load().then(
      (data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      },
      (reason: unknown) => {
        if (cancelled) return;
        const message =
          reason instanceof Error && reason.message ? reason.message : m.common.loadFailed;
        setState((s) => ({ ...s, error: message, loading: false }));
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `deps` is the caller's dependency list
  }, [...deps, tick]);
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    setTick((t) => t + 1);
  }, []);
  return { ...state, reload };
}
