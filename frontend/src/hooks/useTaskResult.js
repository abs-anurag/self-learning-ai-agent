/**
 * useTaskResult — fetch the terminal result for a completed task.
 *
 * Source of truth: BLUEPRINT.md §15 GET /tasks/{id}/result
 *
 * The endpoint returns HTTP 409 when the task is not yet in a terminal state.
 * This hook surfaces that cleanly via { notComplete: true } rather than an error.
 *
 * Exposes:
 *   result      — TaskResultResponse or null
 *   loading     — true while fetching
 *   error       — Error details or null
 *   notComplete — true when task is still pending/running (HTTP 409)
 *   refresh     — Re-fetch the result
 */

import { useState, useEffect, useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useAgentStore } from '../store/agentStore.js';

/**
 * @param {string|null} taskId — UUID of the task, or null to skip
 * @returns {{ result: object|null, loading: boolean, error: object|null, notComplete: boolean, refresh: function }}
 */
export function useTaskResult(taskId) {
  const [notComplete, setNotComplete] = useState(false);

  const { taskResult, taskResultLoading, taskResultError, fetchTaskResult, clearTaskResult } =
    useAgentStore(useShallow((s) => ({
      taskResult: s.taskResult,
      taskResultLoading: s.taskResultLoading,
      taskResultError: s.taskResultError,
      fetchTaskResult: s.fetchTaskResult,
      clearTaskResult: s.clearTaskResult,
    })));

  const refresh = useCallback(async () => {
    if (!taskId) return;
    setNotComplete(false);
    try {
      const data = await fetchTaskResult(taskId);
      if (data?._notComplete) setNotComplete(true);
    } catch {
      // Error is stored in taskResultError by the store action
    }
  }, [taskId, fetchTaskResult]);

  useEffect(() => {
    if (!taskId) {
      clearTaskResult();
      setNotComplete(false);
      return;
    }
    refresh();
    return () => {
      clearTaskResult();
      setNotComplete(false);
    };
  }, [taskId, refresh, clearTaskResult]);

  return {
    result: taskResult?.task_id === taskId ? taskResult : null,
    loading: taskResultLoading,
    error: taskResultError,
    notComplete,
    refresh,
  };
}

export default useTaskResult;
