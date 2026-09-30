/**
 * useTaskList — fetch and navigate the paginated task list.
 *
 * Source of truth: BLUEPRINT.md §15 GET /tasks
 *
 * Exposes:
 *   tasks       — Array of task summary items
 *   loading     — true while fetching
 *   error       — Error details or null
 *   pagination  — { page, pageSize, total }
 *   fetchPage   — Fetch a specific page
 *   refresh     — Re-fetch the current page
 */

import { useEffect, useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useAgentStore } from '../store/agentStore.js';

/**
 * @param {object}  [options]
 * @param {number}  [options.page=1]
 * @param {number}  [options.pageSize=20]
 * @param {boolean} [options.autoFetch=true] — Automatically fetch on mount
 */
export function useTaskList({ page = 1, pageSize = 20, autoFetch = true } = {}) {
  const { tasks, tasksLoading, tasksError, tasksPagination, fetchTasks } = useAgentStore(useShallow((s) => ({
    tasks: s.tasks,
    tasksLoading: s.tasksLoading,
    tasksError: s.tasksError,
    tasksPagination: s.tasksPagination,
    fetchTasks: s.fetchTasks,
  })));

  const fetchPage = useCallback(
    (p = 1, ps = pageSize) => fetchTasks(p, ps),
    [fetchTasks, pageSize]
  );

  const refresh = useCallback(() => {
    fetchTasks(tasksPagination.page, tasksPagination.pageSize);
  }, [fetchTasks, tasksPagination.page, tasksPagination.pageSize]);

  useEffect(() => {
    if (autoFetch) fetchTasks(page, pageSize);
  }, [autoFetch, page, pageSize, fetchTasks]);

  return {
    tasks,
    loading: tasksLoading,
    error: tasksError,
    pagination: tasksPagination,
    fetchPage,
    refresh,
  };
}

export default useTaskList;
