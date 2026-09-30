/**
 * useFeedback — submit user feedback for a completed task.
 *
 * Source of truth: BLUEPRINT.md §15 POST /tasks/{id}/feedback
 *
 * Exposes:
 *   submit  — async (rating: number, comment?: string) => void
 *   loading — true while submitting
 *   error   — Error details or null
 *   result  — { feedback_id, status } or null after successful submission
 *   reset   — Clear the feedback state
 */

import { useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useAgentStore } from '../store/agentStore.js';

/**
 * @param {string} taskId — UUID of the task to submit feedback for
 * @returns {{ submit: function, loading: boolean, error: object|null, result: object|null, reset: function }}
 */
export function useFeedback(taskId) {
  const { feedbackLoading, feedbackError, feedbackResult, submitFeedback, clearFeedback } =
    useAgentStore(useShallow((s) => ({
      feedbackLoading: s.feedbackLoading,
      feedbackError: s.feedbackError,
      feedbackResult: s.feedbackResult,
      submitFeedback: s.submitFeedback,
      clearFeedback: s.clearFeedback,
    })));

  const submit = useCallback(
    async (rating, comment = null) => {
      if (!taskId) return;
      return submitFeedback(taskId, rating, comment);
    },
    [taskId, submitFeedback]
  );

  return {
    submit,
    loading: feedbackLoading,
    error: feedbackError,
    result: feedbackResult,
    reset: clearFeedback,
  };
}

export const useTaskFeedback = useFeedback;

export default useFeedback;
