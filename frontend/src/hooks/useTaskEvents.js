/**
 * useTaskEvents — manage real-time WebSocket event stream for a task.
 *
 * Source of truth: BLUEPRINT.md §15 WS /ws/tasks/{id},
 *                  §16 WebSocket Reconnect & Code 1013 Handling.
 *
 * This hook:
 *  - Retrieves the API key from the environment (never from props)
 *  - Connects the WebSocket on mount / taskId change
 *  - Routes events through the store's receiveEvent (with deduplication)
 *  - Tracks connection status and reconnecting flag in the store
 *  - Disconnects cleanly on unmount or taskId change
 *  - Exposes a manual disconnect/reconnect interface
 *
 * Exposes:
 *   events          — Ordered array of received EventEnvelopes
 *   connectionStatus — 'connecting'|'connected'|'disconnected'|'reconnecting'|'failed'
 *   latestSequence  — Highest accepted sequence number (used for reconnect)
 *   reconnecting    — true when an automatic reconnect is pending
 *   replayLoading   — true while the HTTP event-history fallback is loading
 *   wsError         — Last WebSocket error details or null
 *   connect         — Manually initiate a connection
 *   disconnect      — Intentionally disconnect (will not auto-reconnect)
 *   replayEvents    — Manually replay durable events over HTTP
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { getApiKey } from '../api/http.js';
import { taskApi } from '../api/taskApi.js';
import { useAgentStore } from '../store/agentStore.js';
import { createWebSocketConnection } from '../api/ws.js';

/**
 * @param {string|null} taskId — UUID of the task to subscribe to, or null to skip
 * @returns {{
 *   events: Array,
 *   connectionStatus: string,
 *   latestSequence: number,
 *   reconnecting: boolean,
 *   replayLoading: boolean,
 *   wsError: object|null,
 *   connect: function,
 *   disconnect: function,
 *   replayEvents: function,
 * }}
 */
export function useTaskEvents(taskId) {
  /** Ref holding the current WsHandle — allows cleanup without stale closure issues. */
  const wsHandleRef = useRef(null);
  const [replayLoading, setReplayLoading] = useState(false);

  const {
    events,
    latestSequence,
    connectionStatus,
    reconnecting,
    wsError,
    clearEvents,
  } = useAgentStore(useShallow((s) => ({
    events: s.events,
    latestSequence: s.latestSequence,
    connectionStatus: s.connectionStatus,
    reconnecting: s.reconnecting,
    wsError: s.wsError,
    clearEvents: s.clearEvents,
  })));

  // Retrieve API key from environment — never logged
  const apiKey = getApiKey();

  // -------------------------------------------------------------------------
  // Disconnect helper — clean up the current WS handle
  // -------------------------------------------------------------------------

  const disconnect = useCallback(() => {
    if (wsHandleRef.current) {
      wsHandleRef.current.disconnect();
      wsHandleRef.current = null;
    }
  }, []);

  const applyEvent = useCallback((envelope) => {
    const applied = useAgentStore.getState().receiveEvent(envelope);
    if (applied && (envelope.event_type === 'task_completed' || envelope.event_type === 'task_failed')) {
      useAgentStore.getState().fetchTaskResult(taskId).catch(() => {});
    }
    return applied;
  }, [taskId]);

  const replayEvents = useCallback(async () => {
    if (!taskId) return false;

    setReplayLoading(true);
    let afterSequence = useAgentStore.getState().latestSequence;
    try {
      while (true) {
        const batch = await taskApi.getTaskEvents(taskId, afterSequence, 1000);
        if (!Array.isArray(batch)) throw new Error('Invalid event replay response.');

        const previousAfterSequence = afterSequence;
        let progressed = false;
        for (const envelope of batch) {
          if (!Number.isInteger(envelope?.sequence)) throw new Error('Invalid event sequence.');
          const currentSequence = useAgentStore.getState().latestSequence;
          if (envelope.sequence <= currentSequence) {
            const nextSequence = Math.max(afterSequence, envelope.sequence, currentSequence);
            progressed ||= nextSequence > afterSequence;
            afterSequence = nextSequence;
            continue;
          }
          if (envelope.sequence !== currentSequence + 1 || envelope.task_id !== taskId) {
            throw new Error('Event replay is not contiguous for this task.');
          }
          if (!applyEvent(envelope)) throw new Error('Event replay could not be applied.');
          afterSequence = envelope.sequence;
          progressed = true;
        }

        if (batch.length < 1000) break;
        if (!progressed || afterSequence <= previousAfterSequence) {
          throw new Error('Event replay made no progress.');
        }
      }
      return true;
    } catch (error) {
      useAgentStore.getState().setWsError({
        code: error?.code ?? 'EVENT_REPLAY_FAILED',
        message: 'Could not recover task events from the event history endpoint.',
      });
      return false;
    } finally {
      setReplayLoading(false);
    }
  }, [taskId, applyEvent]);

  // -------------------------------------------------------------------------
  // Connect helper — creates a new WebSocket connection
  // -------------------------------------------------------------------------

  const connect = useCallback(() => {
    if (!taskId) return;
    if (!apiKey) {
      useAgentStore.getState().setConnectionStatus('failed');
      useAgentStore.getState().setWsError({
        code: 'MISSING_API_KEY',
        message: 'WebSocket authentication is unavailable. Configure the API key before connecting.',
      });
      return;
    }

    // Disconnect any existing connection before creating a new one
    disconnect();

    const handle = createWebSocketConnection({
      taskId,
      apiKey,
      // Resume from the latest known sequence to recover missed events
      initialSequence: useAgentStore.getState().latestSequence,
      onEvent: applyEvent,
      onConnectionStatus: (status) => {
        useAgentStore.getState().setConnectionStatus(status);
      },
      onError: (error) => {
        useAgentStore.getState().setWsError(error);
        if (error.code === 'WS_MAX_RETRIES') replayEvents();
      },
    });

    wsHandleRef.current = handle;
  }, [taskId, apiKey, applyEvent, disconnect, replayEvents]);

  // -------------------------------------------------------------------------
  // Effect — manage WebSocket lifecycle with taskId changes
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (!taskId) return;

    // Clear prior events when switching tasks
    clearEvents();

    // Open the connection
    connect();

    // Cleanup: disconnect when component unmounts or taskId changes
    return () => {
      disconnect();
    };
  }, [taskId, clearEvents, connect, disconnect]);

  return {
    events,
    connectionStatus,
    latestSequence,
    error: wsError,
    reconnecting,
    replayLoading,
    connect,
    disconnect,
    replayEvents,
  };
}

export default useTaskEvents;
