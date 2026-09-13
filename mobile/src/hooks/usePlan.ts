import { useCallback, useEffect, useState } from 'react';

import { ApiError, getDemoPlan } from '@/api/client';
import type { RunResult } from '@/api/types';

export interface PlanState {
  run: RunResult | null;
  loading: boolean;
  /** Human-readable, already suitable for both display and announcement. */
  error: string | null;
  reload: () => void;
}

/**
 * Loads the current week from `GET /api/demo`.
 *
 * `/api/demo` rather than `POST /api/plan` on purpose: it takes no body, needs
 * no auth in either mode, and returns the same `RunResult` envelope, so the
 * phone can open cold without deciding a scenario first. A later phase that
 * wants live planning swaps in `createPlan({ scenario })` here — the returned
 * shape does not change.
 *
 * One fetch is shared per screen mount; there is no global cache yet, so Home
 * and Week each load their own copy. That is a deliberate omission, not an
 * oversight: adding a store before there is a second consumer of the data would
 * be guesswork.
 */
export function usePlan(): PlanState {
  const [run, setRun] = useState<RunResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);

    getDemoPlan(controller.signal)
      .then((result) => {
        if (!active) return;
        setRun(result);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setRun(null);
        setError(caught instanceof ApiError ? caught.message : 'Could not load this week’s plan.');
        setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [attempt]);

  return { run, loading, error, reload };
}
