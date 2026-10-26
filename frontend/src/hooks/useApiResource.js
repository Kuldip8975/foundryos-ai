import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Load data from the API whenever `key` changes.
 *
 * - Cancels the previous request (AbortController) so a slow, stale response
 *   can never overwrite a newer one.
 * - Keeps the last successful data while a reload is in flight
 *   (`loading && data`), so the page doesn't flash; clears it on error so
 *   stale figures are never shown next to an error message.
 * - `enabled: false` skips loading (e.g. while a filter is invalid).
 *
 * @param {(opts: {signal: AbortSignal}) => Promise<any>} fetcher
 * @param {string} key  serialised inputs; a change triggers a reload
 */
export function useApiResource(fetcher, key, { enabled = true } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const controllerRef = useRef(null);

  const load = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fetcherRef.current({ signal: controller.signal });
      if (!controller.signal.aborted) setState({ data, error: null, loading: false });
    } catch (error) {
      if (!controller.signal.aborted) setState({ data: null, error, loading: false });
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      controllerRef.current?.abort();
      setState((s) => ({ ...s, loading: false }));
      return undefined;
    }
    load();
    return () => controllerRef.current?.abort();
  }, [key, enabled, load]);

  return { ...state, reload: load };
}
