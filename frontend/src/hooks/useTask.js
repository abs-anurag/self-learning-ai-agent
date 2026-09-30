/**
 * useTask — fetch and subscribe to a single task.
 *
 * Source of truth: BLUEPRINT.md §15 GET /tasks/{id}
 *
 * Exposes:
 *   task        — Task detail object or null
 *   create      — Create a task and select it as current
 *   loading     — true while fetching
 *   error       — Error details or null
 *   refresh     — Re-fetch the task
 */

import { useEffect, useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useAgentStore } from '../store/agentStore.js';

/**
 * @param {string|null} taskId — UUID of the task to fetch, or null to skip
 * @returns {{ task: object|null, loading: boolean, error: object|null, create: function, refresh: function }}
 */
export function useTask(taskId) {
  const { currentTask, taskLoading, taskError, fetchTask, createTask, clearCurrentTask } = useAgentStore(useShallow((s) => ({
    currentTask: s.currentTask,
    taskLoading: s.taskLoading,
    taskError: s.taskError,
    fetchTask: s.fetchTask,
    createTask: s.createTask,
    clearCurrentTask: s.clearCurrentTask,
  })));

  const refresh = useCallback(() => {
    if (taskId) fetchTask(taskId);
  }, [taskId, fetchTask]);

  const create = useCallback((goal) => createTask(goal), [createTask]);

  useEffect(() => {
    if (!taskId) {
      clearCurrentTask();
      return;
    }
    clearCurrentTask();
    fetchTask(taskId);
  }, [taskId, fetchTask, clearCurrentTask]);

  return {
    task: currentTask?.task_id === taskId ? currentTask : null,
    loading: taskLoading,
    error: taskError,
    create,
    refresh,
  };
}

export default useTask;
