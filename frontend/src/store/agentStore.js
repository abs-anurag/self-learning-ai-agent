/**
 * Zustand state store for the Self-Learning AI Agent dashboard.
 *
 * Source of truth: BLUEPRINT.md §15 (API contracts), §16 (Frontend Architecture).
 *
 * Architecture:
 *   API / WebSocket
 *     ↓
 *   taskApi.js / ws.js
 *     ↓
 *   agentStore  ← you are here
 *     ↓
 *   React hooks (src/hooks/)
 *     ↓
 *   UI components (Frontend Member 1)
 *
 * Slices:
 *   taskSlice    — tasks list, current task, pagination, loading/error
 *   resultSlice  — terminal task result
 *   eventSlice   — real-time events, sequence tracking, WS connection state
 *   recipeSlice  — trusted recipe list, pagination
 *   metricsSlice — aggregate metrics
 *   healthSlice  — API/infrastructure health
 *   feedbackSlice— feedback submission state
 *
 * State exposed to UI:
 *   tasks, currentTask, taskResult
 *   events, latestSequence, connectionStatus, reconnecting
 *   recipes, metrics, health
 *   loading/error variants per slice
 *
 * Status vocabulary is strictly: 'pending', 'running', 'succeeded', 'failed'
 * The value 'completed' is never used. (BLUEPRINT.md §1)
 */

import { create } from 'zustand';
import { taskApi } from '../api/taskApi.js';

// ---------------------------------------------------------------------------
// Slice creators
// ---------------------------------------------------------------------------

// -- Task Slice --------------------------------------------------------------

const createTaskSlice = (set, get) => ({
  // State
  tasks: [],
  currentTask: null,
  tasksLoading: false,
  taskLoading: false,
  tasksError: null,
  taskError: null,
  tasksPagination: { page: 1, pageSize: 20, total: 0 },

  // Actions

  /** Fetch the paginated task list for the authenticated user. */
  fetchTasks: async (page = 1, pageSize = 20) => {
    set({ tasksLoading: true, tasksError: null });
    try {
      const data = await taskApi.listTasks(page, pageSize);
      set({
        tasks: data.items ?? [],
        tasksPagination: {
          page: data.page ?? page,
          pageSize: data.page_size ?? pageSize,
          total: data.total ?? 0,
        },
        tasksLoading: false,
      });
    } catch (err) {
      set({ tasksLoading: false, tasksError: buildError(err) });
    }
  },

  /** Fetch a single task by ID (with run summaries). */
  fetchTask: async (taskId) => {
    set({ taskLoading: true, taskError: null, currentTask: null });
    try {
      const data = await taskApi.getTask(taskId);
      set({ currentTask: data, taskLoading: false });
    } catch (err) {
      set({ taskLoading: false, taskError: buildError(err) });
    }
  },

  /** Create a new task and optimistically add it to the task list. */
  createTask: async (goal) => {
    set({ taskLoading: true, taskError: null });
    try {
      const data = await taskApi.createTask(goal);
      // Prepend the new task stub to the list for immediate UI feedback
      const taskStub = {
        task_id: data.task_id,
        run_id: data.run_id,
        goal,
        status: 'pending',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      set((state) => ({
        tasks: [taskStub, ...state.tasks],
        currentTask: taskStub,
        taskLoading: false,
      }));
      return data;
    } catch (err) {
      set({ taskLoading: false, taskError: buildError(err) });
      throw err;
    }
  },

  /** Set the current task without a network call (e.g., from task list selection). */
  setCurrentTask: (task) => set({ currentTask: task }),

  /** Clear the current task and associated state. */
  clearCurrentTask: () => set({ currentTask: null }),
});

// -- Result Slice ------------------------------------------------------------

const createResultSlice = (set) => ({
  // State
  taskResult: null,
  taskResultLoading: false,
  taskResultError: null,

  /** Fetch the terminal result for a completed task. */
  fetchTaskResult: async (taskId) => {
    set({ taskResultLoading: true, taskResultError: null, taskResult: null });
    try {
      const data = await taskApi.getTaskResult(taskId);
      if (data._notComplete) {
        // Task not yet terminal — leave result null, not an error
        set({ taskResultLoading: false, taskResult: null });
      } else {
        set({ taskResult: data, taskResultLoading: false });
      }
      return data;
    } catch (err) {
      set({ taskResultLoading: false, taskResultError: buildError(err) });
      throw err;
    }
  },

  /** Clear stored task result. */
  clearTaskResult: () => set({ taskResult: null, taskResultError: null }),
});

// -- Event Slice -------------------------------------------------------------

const createEventSlice = (set, get) => ({
  // State

  /** Ordered list of accepted EventEnvelope objects (sequence ascending). */
  events: [],

  /**
   * Highest sequence number successfully received and applied.
   * Used as last_sequence on WebSocket reconnect.
   * Source: BLUEPRINT.md §16.
   */
  latestSequence: 0,

  /** WebSocket connection status string. */
  connectionStatus: 'disconnected',

  /** True while a reconnect attempt is pending. */
  reconnecting: false,

  /** Last WebSocket error details or null. */
  wsError: null,

  // Actions

  /**
   * Process an incoming EventEnvelope.
   * Applies sequence deduplication — duplicate or stale events are silently dropped.
   *
   * BLUEPRINT.md §16:
   * "Client tracks last_seen_sequence and discards any event where
   *  sequence <= last_seen_sequence"
   */
  receiveEvent: (envelope) => {
    const seq = envelope?.sequence;
    if (!Number.isInteger(seq) || seq < 1) return false;

    const current = get();
    if (seq <= current.latestSequence || seq !== current.latestSequence + 1) return false;

    set((state) => {
      const taskStatus = {
        task_started: 'running',
        task_completed: 'succeeded',
        task_failed: 'failed',
      }[envelope.event_type] ?? null;
      const updatedTask = taskStatus
        ? { status: taskStatus, updated_at: envelope.timestamp }
        : null;
      return {
        events: [...state.events, envelope],
        latestSequence: seq,
        ...(updatedTask && state.currentTask?.task_id === envelope.task_id
          ? { currentTask: { ...state.currentTask, ...updatedTask } }
          : {}),
        ...(updatedTask
          ? { tasks: state.tasks.map((task) => task.task_id === envelope.task_id ? { ...task, ...updatedTask } : task) }
          : {}),
      };
    });
    return true;
  },

  /** Update the WebSocket connection status. */
  setConnectionStatus: (status) => {
    set({ connectionStatus: status, reconnecting: status === 'reconnecting' });
  },

  /** Set the reconnecting flag independently if needed. */
  setReconnecting: (reconnecting) => set({ reconnecting }),

  /** Store a WebSocket error. */
  setWsError: (error) => set({ wsError: error }),

  /**
   * Clear events and reset sequence tracking.
   * Call this before subscribing to a new task's event stream.
   */
  clearEvents: () => set({
    events: [],
    latestSequence: 0,
    wsError: null,
    connectionStatus: 'disconnected',
    reconnecting: false,
  }),
});

// -- Recipe Slice ------------------------------------------------------------

const createRecipeSlice = (set) => ({
  // State
  recipes: [],
  recipesLoading: false,
  recipesError: null,
  recipesPagination: { page: 1, pageSize: 20, total: 0 },

  /** Fetch the paginated list of trusted recipes. */
  fetchRecipes: async (page = 1, pageSize = 20) => {
    set({ recipesLoading: true, recipesError: null });
    try {
      const data = await taskApi.getRecipes(page, pageSize);
      set({
        recipes: data.items ?? [],
        recipesPagination: {
          page: data.page ?? page,
          pageSize: data.page_size ?? pageSize,
          total: data.total ?? 0,
        },
        recipesLoading: false,
      });
    } catch (err) {
      set({ recipesLoading: false, recipesError: buildError(err) });
    }
  },
});

// -- Metrics Slice -----------------------------------------------------------

const createMetricsSlice = (set) => ({
  // State
  metrics: null,
  metricsLoading: false,
  metricsError: null,

  /** Fetch aggregate performance metrics. */
  fetchMetrics: async () => {
    set({ metricsLoading: true, metricsError: null });
    try {
      const data = await taskApi.getMetrics();
      set({ metrics: data, metricsLoading: false });
    } catch (err) {
      set({ metricsLoading: false, metricsError: buildError(err) });
    }
  },
});

// -- Health Slice ------------------------------------------------------------

const createHealthSlice = (set) => ({
  // State
  health: null,
  healthLoading: false,
  healthError: null,

  /** Fetch API / infrastructure health. */
  fetchHealth: async () => {
    set({ healthLoading: true, healthError: null });
    try {
      const data = await taskApi.getHealth();
      set({ health: data, healthLoading: false });
    } catch (err) {
      set({ healthLoading: false, healthError: buildError(err) });
    }
  },
});

// -- Feedback Slice ----------------------------------------------------------

const createFeedbackSlice = (set) => ({
  // State
  feedbackLoading: false,
  feedbackError: null,
  feedbackResult: null,

  /** Submit user feedback for a completed task. */
  submitFeedback: async (taskId, rating, comment = null) => {
    set({ feedbackLoading: true, feedbackError: null, feedbackResult: null });
    try {
      const data = await taskApi.submitFeedback(taskId, rating, comment);
      set({ feedbackResult: data, feedbackLoading: false });
      return data;
    } catch (err) {
      set({ feedbackLoading: false, feedbackError: buildError(err) });
      throw err;
    }
  },

  /** Clear feedback state. */
  clearFeedback: () => set({ feedbackLoading: false, feedbackError: null, feedbackResult: null }),
});

// ---------------------------------------------------------------------------
// Error normaliser
// ---------------------------------------------------------------------------

/**
 * Convert an ApiError or generic Error to a plain serialisable error object
 * suitable for storage in Zustand state.
 *
 * @param {import('../api/http.js').ApiError|Error} err
 * @returns {{ code: string, message: string, status: number, requestId: string }}
 */
function buildError(err) {
  if (err && err.name === 'ApiError') {
    return {
      code: err.code ?? 'UNKNOWN_ERROR',
      message: err.message ?? 'An error occurred.',
      status: err.status ?? 0,
      requestId: err.requestId ?? '',
    };
  }
  return {
    code: 'UNKNOWN_ERROR',
    message: err?.message ?? 'An unexpected error occurred.',
    status: 0,
    requestId: '',
  };
}

// ---------------------------------------------------------------------------
// Compose store
// ---------------------------------------------------------------------------

/**
 * The main Zustand store for the Self-Learning AI Agent dashboard.
 *
 * Import and use via:
 *   import { useAgentStore } from '../store/agentStore.js'
 *   const { tasks, fetchTasks } = useAgentStore()
 *
 * Or via typed hooks in src/hooks/
 */
export const useAgentStore = create((set, get) => ({
  ...createTaskSlice(set, get),
  ...createResultSlice(set),
  ...createEventSlice(set, get),
  ...createRecipeSlice(set),
  ...createMetricsSlice(set),
  ...createHealthSlice(set),
  ...createFeedbackSlice(set),
}));

export default useAgentStore;
