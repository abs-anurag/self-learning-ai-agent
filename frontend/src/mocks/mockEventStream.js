/**
 * Mock event stream for Day 3 UI playback.
 *
 * Source of truth: BLUEPRINT.md §14 Event Types, §16 Day 3 mock player,
 *                  §24 Golden A/B Demo Scenario.
 *
 * This module is STRICTLY ISOLATED from production API logic.
 * - Contains only mock fixture data.
 * - Exposes playback utilities; does NOT call fetch() or WebSocket.
 * - Mocks follow the exact production EventEnvelope schema:
 *     event_id, task_id, run_id, user_id, sequence, schema_version,
 *     timestamp, event_type, status, metadata
 * - All 11 allowlisted event types are represented (BLUEPRINT.md §14).
 * - Status vocabulary is strictly: 'pending', 'running', 'succeeded', 'failed'.
 *   The value 'completed' is never used.
 *
 * Replacement with real API:
 *   Simply stop calling playMockEvents() and instead use useTaskEvents()
 *   from src/hooks/useTaskEvents.js, which connects to the real WebSocket.
 *
 * Event types (BLUEPRINT.md §14):
 *   task_started, planning_started, memory_retrieved, tool_started,
 *   tool_completed, evaluation_completed, reflection_completed,
 *   learning_candidate_created, learning_saved, task_completed, task_failed
 */

// ---------------------------------------------------------------------------
// Fixture UUIDs (deterministic, safe to commit — not real credentials)
// ---------------------------------------------------------------------------

const MOCK_TASK_ID = 'aaaaaaaa-0000-4000-8000-000000000001';
const MOCK_RUN_ID  = 'bbbbbbbb-0000-4000-8000-000000000001';
const MOCK_USER_ID = 'cccccccc-0000-4000-8000-000000000001';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isoNow(offsetSeconds = 0) {
  return new Date(Date.now() + offsetSeconds * 1000).toISOString();
}

function mockEnvelope(sequence, event_type, status, metadata = {}) {
  return {
    event_id: `dddddddd-0000-4000-${String(sequence).padStart(4, '0')}-000000000001`,
    task_id: MOCK_TASK_ID,
    run_id: MOCK_RUN_ID,
    user_id: MOCK_USER_ID,
    sequence,
    schema_version: '1.0',
    timestamp: isoNow(sequence),
    event_type,
    status,
    metadata,
  };
}

// ---------------------------------------------------------------------------
// Mock event fixture — Run A (Baseline, no prior recipe)
// Mirrors BLUEPRINT.md §24 Golden A/B Demo Scenario Run A exactly.
// ---------------------------------------------------------------------------

/**
 * All 11 production event types in sequence order (ascending).
 * Models Run A from the Golden Demo: 2-iteration run that succeeds and
 * promotes a trusted recipe.
 *
 * @type {Array<EventEnvelope>}
 */
export const MOCK_EVENTS_RUN_A = [
  // 1. task_started
  mockEnvelope(1, 'task_started', 'running', {
    task_type: 'math',
    goal: 'Calculate the compound interest on $10,000 at 5% annual rate for 3 years, compounded monthly.',
  }),

  // 2. memory_retrieved — 0 recipes retrieved (baseline run)
  mockEnvelope(2, 'memory_retrieved', 'running', {
    hits: 0,
    task_type: 'math',
  }),

  // 3. planning_started — iteration 1
  mockEnvelope(3, 'planning_started', 'running', {
    iteration: 1,
    plan_summary: 'Calculate using simple compound interest: 10000 * (1 + 0.05) ** 3',
  }),

  // 4. tool_started — calculator
  mockEnvelope(4, 'tool_started', 'running', {
    tool_name: 'calculator',
    iteration: 1,
    input_expression: '10000 * (1 + 0.05) ** 3',
  }),

  // 5. tool_completed — calculator result (wrong formula)
  mockEnvelope(5, 'tool_completed', 'running', {
    tool_name: 'calculator',
    iteration: 1,
    status: 'succeeded',
    result_summary: '11576.25',
  }),

  // 6. evaluation_completed — iteration 1 failed (wrong answer)
  mockEnvelope(6, 'evaluation_completed', 'running', {
    iteration_count: 1,
    task_success: false,
    deterministic_pass: false,
    tool_success: true,
    judge_score: 4.5,
    tool_call_count: 1,
  }),

  // 7. reflection_completed
  mockEnvelope(7, 'reflection_completed', 'running', {
    iteration: 1,
    diagnosis_summary: 'Incorrect formula: compound frequency not applied. Required: A = P*(1 + r/n)**(n*t)',
  }),

  // 8. planning_started — iteration 2 (replan)
  mockEnvelope(8, 'planning_started', 'running', {
    iteration: 2,
    plan_summary: 'Apply correct formula: 10000 * (1 + 0.05/12) ** (12*3)',
  }),

  // (tool_started for iteration 2 — same tool)
  mockEnvelope(9, 'tool_started', 'running', {
    tool_name: 'calculator',
    iteration: 2,
    input_expression: '10000 * (1 + 0.05/12) ** (12*3)',
  }),

  // (tool_completed — correct result)
  mockEnvelope(10, 'tool_completed', 'running', {
    tool_name: 'calculator',
    iteration: 2,
    status: 'succeeded',
    result_summary: '11614.72',
  }),

  // evaluation_completed — iteration 2 succeeded
  mockEnvelope(11, 'evaluation_completed', 'succeeded', {
    iteration_count: 2,
    task_success: true,
    deterministic_pass: true,
    tool_success: true,
    judge_score: 9.0,
    tool_call_count: 1,
  }),

  // learning_candidate_created
  mockEnvelope(12, 'learning_candidate_created', 'succeeded', {
    task_type: 'math',
    problem_pattern: 'compound interest with compounding frequency',
    recommended_strategy: 'Apply formula A = P*(1 + r/n)**(n*t) directly via calculator',
  }),

  // learning_saved — promoted to trusted recipe
  mockEnvelope(13, 'learning_saved', 'succeeded', {
    task_type: 'math',
    recipe_id: 'eeeeeeee-0000-4000-8000-000000000001',
    problem_pattern: 'compound interest with compounding frequency',
  }),

  // task_completed
  mockEnvelope(14, 'task_completed', 'succeeded', {
    final_response_summary: 'The compound interest is $1,614.72.',
    iterations_used: 2,
  }),
];

// ---------------------------------------------------------------------------
// Mock event fixture — Run B (Learned run, recipe retrieved)
// Mirrors BLUEPRINT.md §24 Golden A/B Demo Scenario Run B exactly.
// ---------------------------------------------------------------------------

const MOCK_TASK_ID_B = 'aaaaaaaa-0000-4000-8000-000000000002';
const MOCK_RUN_ID_B  = 'bbbbbbbb-0000-4000-8000-000000000002';

function mockEnvelopeB(sequence, event_type, status, metadata = {}) {
  return {
    event_id: `eeeeeeee-0000-4000-${String(sequence).padStart(4, '0')}-000000000002`,
    task_id: MOCK_TASK_ID_B,
    run_id: MOCK_RUN_ID_B,
    user_id: MOCK_USER_ID,
    sequence,
    schema_version: '1.0',
    timestamp: isoNow(sequence + 100),
    event_type,
    status,
    metadata,
  };
}

/**
 * Mock events for Run B — recipe retrieved, succeeds in 1 iteration.
 * @type {Array<EventEnvelope>}
 */
export const MOCK_EVENTS_RUN_B = [
  mockEnvelopeB(1, 'task_started', 'running', {
    task_type: 'math',
    goal: 'Calculate the compound interest on $5,000 at 7% annual rate for 5 years, compounded quarterly.',
  }),

  mockEnvelopeB(2, 'memory_retrieved', 'running', {
    hits: 1,
    task_type: 'math',
    recipe_summary: 'Apply A = P*(1 + r/n)**(n*t) — compound interest with frequency',
  }),

  mockEnvelopeB(3, 'planning_started', 'running', {
    iteration: 1,
    plan_summary: 'Retrieved recipe suggests formula A = P*(1 + r/n)**(n*t). Applying: 5000 * (1 + 0.07/4)**(4*5)',
  }),

  mockEnvelopeB(4, 'tool_started', 'running', {
    tool_name: 'calculator',
    iteration: 1,
    input_expression: '5000 * (1 + 0.07/4) ** (4*5)',
  }),

  mockEnvelopeB(5, 'tool_completed', 'running', {
    tool_name: 'calculator',
    iteration: 1,
    status: 'succeeded',
    result_summary: '7073.89',
  }),

  mockEnvelopeB(6, 'evaluation_completed', 'succeeded', {
    iteration_count: 1,
    task_success: true,
    deterministic_pass: true,
    tool_success: true,
    judge_score: 9.2,
    tool_call_count: 1,
  }),

  // learning_candidate_created — but will be skipped (duplicate recipe)
  mockEnvelopeB(7, 'learning_candidate_created', 'succeeded', {
    task_type: 'math',
    learning_decision: 'skip',
    skip_reason: 'Duplicate recipe detected (similarity >= 0.90)',
  }),

  mockEnvelopeB(8, 'task_completed', 'succeeded', {
    final_response_summary: 'The compound interest after 5 years is $2,073.89 (total: $7,073.89).',
    iterations_used: 1,
  }),
];

// ---------------------------------------------------------------------------
// Mock event fixture — Failed run (demonstrates task_failed path)
// ---------------------------------------------------------------------------

const MOCK_TASK_ID_FAIL = 'aaaaaaaa-0000-4000-8000-000000000003';
const MOCK_RUN_ID_FAIL  = 'bbbbbbbb-0000-4000-8000-000000000003';

function mockEnvelopeFail(sequence, event_type, status, metadata = {}) {
  return {
    event_id: `ffffffff-0000-4000-${String(sequence).padStart(4, '0')}-000000000003`,
    task_id: MOCK_TASK_ID_FAIL,
    run_id: MOCK_RUN_ID_FAIL,
    user_id: MOCK_USER_ID,
    sequence,
    schema_version: '1.0',
    timestamp: isoNow(sequence + 200),
    event_type,
    status,
    metadata,
  };
}

/**
 * Mock events for a failed run (max iterations exhausted).
 * @type {Array<EventEnvelope>}
 */
export const MOCK_EVENTS_FAILED = [
  mockEnvelopeFail(1, 'task_started', 'running', {
    task_type: 'research',
    goal: 'Find the current population of Mars.',
  }),

  mockEnvelopeFail(2, 'memory_retrieved', 'running', { hits: 0, task_type: 'research' }),
  mockEnvelopeFail(3, 'planning_started', 'running', { iteration: 1 }),
  mockEnvelopeFail(4, 'tool_started', 'running', { tool_name: 'web_search', iteration: 1 }),
  mockEnvelopeFail(5, 'tool_completed', 'running', {
    tool_name: 'web_search',
    iteration: 1,
    status: 'succeeded',
    result_summary: 'No reliable source found for Mars population.',
  }),
  mockEnvelopeFail(6, 'evaluation_completed', 'running', {
    iteration_count: 1,
    task_success: false,
    deterministic_pass: false,
    tool_success: true,
    judge_score: 2.0,
    tool_call_count: 1,
  }),
  mockEnvelopeFail(7, 'reflection_completed', 'running', {
    iteration: 1,
    diagnosis_summary: 'Mars is not inhabited; task is unanswerable.',
  }),

  // Iterations 2 & 3 abbreviated
  mockEnvelopeFail(8, 'planning_started', 'running', { iteration: 2 }),
  mockEnvelopeFail(9, 'evaluation_completed', 'running', {
    iteration_count: 2,
    task_success: false,
    judge_score: 2.0,
    tool_call_count: 1,
  }),
  mockEnvelopeFail(10, 'reflection_completed', 'running', { iteration: 2, diagnosis_summary: 'Still unanswerable.' }),
  mockEnvelopeFail(11, 'planning_started', 'running', { iteration: 3 }),
  mockEnvelopeFail(12, 'evaluation_completed', 'failed', {
    iteration_count: 3,
    task_success: false,
    judge_score: 2.0,
    tool_call_count: 1,
  }),

  // task_failed — max iterations
  mockEnvelopeFail(13, 'task_failed', 'failed', {
    termination_reason: 'max_iterations',
    message: 'Task could not be solved within 3 iterations.',
  }),
];

// ---------------------------------------------------------------------------
// Playback utilities
// ---------------------------------------------------------------------------

/**
 * Unique sentinel for playback state.
 * @private
 */
let _playbackTimerId = null;

/**
 * Play a sequence of mock events to simulate real-time delivery.
 * Events are delivered in sequence order at the given interval.
 *
 * Isolation guarantee: this function never calls fetch() or WebSocket.
 * It is a direct synchronous/async simulation for Day 3 UI development.
 *
 * @param {object}   options
 * @param {Array}    [options.events=MOCK_EVENTS_RUN_A] — Events to play back
 * @param {number}   [options.intervalMs=800]           — Delay between events (ms)
 * @param {function} options.onEvent                    — Called with each EventEnvelope
 * @param {function} [options.onComplete]               — Called when all events delivered
 * @param {function} [options.onConnectionStatus]       — Called with simulated status strings
 */
export function playMockEvents({
  events = MOCK_EVENTS_RUN_A,
  intervalMs = 800,
  onEvent,
  onComplete,
  onConnectionStatus,
} = {}) {
  // Clear any existing playback
  stopMockEvents();

  if (typeof onConnectionStatus === 'function') {
    onConnectionStatus('connecting');
    setTimeout(() => onConnectionStatus('connected'), 100);
  }

  // Sort ascending by sequence to guarantee ordering contract
  const sorted = [...events].sort((a, b) => a.sequence - b.sequence);
  let index = 0;

  function deliverNext() {
    if (index >= sorted.length) {
      _playbackTimerId = null;
      if (typeof onConnectionStatus === 'function') onConnectionStatus('disconnected');
      if (typeof onComplete === 'function') onComplete();
      return;
    }
    if (typeof onEvent === 'function') {
      try {
        onEvent(sorted[index]);
      } catch {
        // Prevent callback errors from breaking playback
      }
    }
    index++;
    _playbackTimerId = setTimeout(deliverNext, intervalMs);
  }

  // Slight delay before first event to simulate connection handshake
  _playbackTimerId = setTimeout(deliverNext, 150);
}

/**
 * Stop active mock event playback.
 */
export function stopMockEvents() {
  if (_playbackTimerId !== null) {
    clearTimeout(_playbackTimerId);
    _playbackTimerId = null;
  }
}

/**
 * Check whether mock playback is currently active.
 * @returns {boolean}
 */
export function isMockPlaybackActive() {
  return _playbackTimerId !== null;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export const MOCK_TASK_IDS = {
  runA: MOCK_TASK_ID,
  runB: MOCK_TASK_ID_B,
  failed: MOCK_TASK_ID_FAIL,
};

export const MOCK_RUN_IDS = {
  runA: MOCK_RUN_ID,
  runB: MOCK_RUN_ID_B,
  failed: MOCK_RUN_ID_FAIL,
};

export default {
  MOCK_EVENTS_RUN_A,
  MOCK_EVENTS_RUN_B,
  MOCK_EVENTS_FAILED,
  playMockEvents,
  stopMockEvents,
  isMockPlaybackActive,
  MOCK_TASK_IDS,
  MOCK_RUN_IDS,
};
