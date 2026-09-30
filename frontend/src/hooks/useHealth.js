/**
 * useHealth — fetch API and infrastructure health status.
 *
 * Source of truth: BLUEPRINT.md §15 GET /health
 *
 * Exposes:
 *   health  — { status, database, redis } or null
 *   loading — true while fetching
 *   error   — Error details or null
 *   refresh — Re-fetch health
 */

import { useEffect, useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useAgentStore } from '../store/agentStore.js';

/**
 * @param {object}  [options]
 * @param {boolean} [options.autoFetch=true]
 */
export function useHealth({ autoFetch = true } = {}) {
  const { health, healthLoading, healthError, fetchHealth } = useAgentStore(useShallow((s) => ({
    health: s.health,
    healthLoading: s.healthLoading,
    healthError: s.healthError,
    fetchHealth: s.fetchHealth,
  })));

  const refresh = useCallback(() => fetchHealth(), [fetchHealth]);

  useEffect(() => {
    if (autoFetch) fetchHealth();
  }, [autoFetch]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    health,
    loading: healthLoading,
    error: healthError,
    refresh,
  };
}

export default useHealth;
