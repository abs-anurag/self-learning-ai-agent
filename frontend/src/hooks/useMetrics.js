/**
 * useMetrics — fetch aggregate performance metrics.
 *
 * Source of truth: BLUEPRINT.md §15 GET /metrics
 *
 * Exposes:
 *   metrics — MetricsResponse object or null
 *   loading — true while fetching
 *   error   — Error details or null
 *   refresh — Re-fetch metrics
 */

import { useEffect, useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useAgentStore } from '../store/agentStore.js';

/**
 * @param {object}  [options]
 * @param {boolean} [options.autoFetch=true]
 */
export function useMetrics({ autoFetch = true } = {}) {
  const { metrics, metricsLoading, metricsError, fetchMetrics } = useAgentStore(useShallow((s) => ({
    metrics: s.metrics,
    metricsLoading: s.metricsLoading,
    metricsError: s.metricsError,
    fetchMetrics: s.fetchMetrics,
  })));

  const refresh = useCallback(() => fetchMetrics(), [fetchMetrics]);

  useEffect(() => {
    if (autoFetch) fetchMetrics();
  }, [autoFetch]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    metrics,
    loading: metricsLoading,
    error: metricsError,
    refresh,
  };
}

export default useMetrics;
