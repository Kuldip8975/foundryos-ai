import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchLiveness, fetchReadiness } from '../api/health.js';

/**
 * Checks backend connectivity: liveness first, then readiness.
 *
 * phase:
 *   'loading'       request in flight
 *   'ready'         API alive, database reachable, migrations at head
 *   'not_ready'     API alive but a readiness check failed (see readiness.checks)
 *   'unreachable'   API could not be reached or returned an error
 *   'misconfigured' frontend API URL is missing/invalid
 */
export function useBackendStatus() {
  const [state, setState] = useState({
    phase: 'loading',
    liveness: null,
    readiness: null,
    error: null,
    checkedAt: null,
  });
  const controllerRef = useRef(null);

  const check = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState((s) => ({ ...s, phase: 'loading', error: null }));

    try {
      const liveness = await fetchLiveness({ signal: controller.signal });
      const readiness = await fetchReadiness({ signal: controller.signal });
      if (controller.signal.aborted) return;
      setState({
        phase: readiness.status === 'ready' ? 'ready' : 'not_ready',
        liveness,
        readiness,
        error: null,
        checkedAt: new Date(),
      });
    } catch (error) {
      if (controller.signal.aborted) return;
      setState({
        phase: error?.kind === 'config' ? 'misconfigured' : 'unreachable',
        liveness: null,
        readiness: null,
        error,
        checkedAt: new Date(),
      });
    }
  }, []);

  useEffect(() => {
    check();
    return () => controllerRef.current?.abort();
  }, [check]);

  return { ...state, refresh: check };
}
