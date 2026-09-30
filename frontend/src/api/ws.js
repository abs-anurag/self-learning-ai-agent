/**
 * WebSocket client for the Self-Learning AI Agent real-time event stream.
 *
 * Source of truth: BLUEPRINT.md §15 WS /ws/tasks/{id},
 *                  §16 Frontend Architecture (WebSocket Reconnect & Code 1013 Handling).
 *
 * Contract:
 *   /ws/tasks/{task_id}?api_key={key}&last_sequence={seq}
 *
 * This module owns:
 *  - Connection establishment
 *  - Connection state tracking
 *  - Incoming event parsing
 *  - Sequence number extraction and validation
 *  - Duplicate detection (skip if sequence <= latestSequence)
 *  - Stale event handling (skip out-of-order events)
 *  - Reconnection with last_sequence recovery
 *  - Bounded exponential back-off
 *  - Prevention of multiple simultaneous connections
 *  - Prevention of stacking reconnect timers
 *  - Clean intentional disconnect (does NOT reconnect)
 *  - Server close-code handling:
 *      1008 Policy Violation  → auth failure → do NOT reconnect
 *      1013 Try Again Later   → buffer overflow → reconnect immediately
 *      1000 Normal Closure    → intentional → do NOT reconnect
 *      other                  → network drop → exponential back-off reconnect
 *  - Malformed message handling (no crash, error surfaced via onError)
 *
 * Security:
 *  - The API key travels in the WebSocket query string.
 *    Per BLUEPRINT.md §17, this is accepted for the classroom MVP due to
 *    browser WebSocket header constraints.  WSS must be enforced outside
 *    localhost.  The key is NEVER logged by this client.
 *
 * IMPORTANT: This module does NOT touch any UI components.
 * Expose the returned handle to React hooks (src/hooks/useTaskEvents.js).
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Close codes per BLUEPRINT.md §15 WS specification.
 * 1008 = Policy Violation (auth failure — do not reconnect)
 * 1013 = Try Again Later (buffer overflow — reconnect immediately with last_sequence)
 * 1000 = Normal Closure (intentional — do not reconnect)
 */
const WS_CODE_NORMAL_CLOSURE     = 1000;
const WS_CODE_POLICY_VIOLATION   = 1008;
const WS_CODE_TRY_AGAIN_LATER    = 1013;

/** Maximum number of reconnect attempts per connection session. */
const MAX_RECONNECT_ATTEMPTS = 10;

/**
 * Exponential back-off delays (ms).
 * Attempt 1→500ms, 2→1000ms, 3→2000ms, 4→4000ms, 5→8000ms, 6+→30000ms.
 */
const BACKOFF_BASE_MS  = 500;
const BACKOFF_MAX_MS   = 30_000;
const BACKOFF_1013_MS  = 200;  // Nearly-immediate retry for buffer-overflow reconnect

const EVENT_TYPES = new Set([
  'task_started',
  'planning_started',
  'memory_retrieved',
  'tool_started',
  'tool_completed',
  'evaluation_completed',
  'reflection_completed',
  'learning_candidate_created',
  'learning_saved',
  'task_completed',
  'task_failed',
]);
const EVENT_STATUSES = new Set(['pending', 'running', 'succeeded', 'failed']);
const TERMINAL_EVENTS = new Set(['task_completed', 'task_failed']);
const EVENT_FIELDS = [
  'event_id', 'task_id', 'run_id', 'user_id', 'sequence', 'schema_version',
  'timestamp', 'event_type', 'status', 'metadata',
];

// ---------------------------------------------------------------------------
// Connection state vocabulary
// ---------------------------------------------------------------------------

/**
 * @typedef {'connecting'|'connected'|'disconnected'|'reconnecting'|'failed'} ConnectionStatus
 */

// ---------------------------------------------------------------------------
// WebSocket connection handle type (returned by createWebSocketConnection)
// ---------------------------------------------------------------------------

/**
 * @typedef {object} WsHandle
 * @property {() => void} disconnect — Clean intentional disconnect; disables reconnect.
 * @property {() => number} getLatestSequence — Current highest accepted sequence number.
 * @property {() => ConnectionStatus} getStatus — Current connection status string.
 */

// ---------------------------------------------------------------------------
// Main factory
// ---------------------------------------------------------------------------

/**
 * Create and manage a WebSocket connection to the agent event stream.
 *
 * @param {object}   options
 * @param {string}   options.taskId            — UUID of the task to subscribe to
 * @param {string}   options.apiKey            — Plaintext API key (not logged)
 * @param {number}   [options.initialSequence=0] — Resume from this sequence number
 * @param {function} options.onEvent           — Called with each valid new EventEnvelope object
 * @param {function} options.onConnectionStatus — Called with ConnectionStatus string on change
 * @param {function} [options.onError]         — Called with error details {code, message}
 *
 * @returns {WsHandle}
 *
 * BLUEPRINT.md §15 WS endpoint:
 *   /ws/tasks/{task_id}?api_key={key}&last_sequence={seq}
 */
export function createWebSocketConnection({
  taskId,
  apiKey,
  initialSequence = 0,
  onEvent,
  onConnectionStatus,
  onError,
}) {
  // -------------------------------------------------------------------------
  // Mutable state (private to this closure)
  // -------------------------------------------------------------------------

  /** @type {WebSocket|null} */
  let ws = null;

  /** Highest sequence number accepted and applied. */
  let latestSequence = initialSequence;

  /** Number of consecutive reconnect attempts (resets on successful connect). */
  let reconnectAttempts = 0;
  let overflowReconnectAttempts = 0;

  /** True after disconnect() is called — prevents any further reconnect. */
  let intentionalDisconnect = false;
  let terminalEventReceived = false;

  /** Handle returned by setTimeout for the pending reconnect (if any). */
  let reconnectTimerId = null;

  /** @type {ConnectionStatus} */
  let currentStatus = 'disconnected';

  // -------------------------------------------------------------------------
  // Internal helpers
  // -------------------------------------------------------------------------

  function emitStatus(status) {
    if (status === currentStatus) return;
    currentStatus = status;
    try {
      onConnectionStatus(status);
    } catch {
      // Never allow callback exceptions to break connection management
    }
  }

  function emitError(code, message) {
    if (typeof onError !== 'function') return;
    try {
      onError({ code, message });
    } catch {
      // Ignore
    }
  }

  /** Calculate exponential back-off delay for the given attempt number (0-based). */
  function backoffDelay(attempt) {
    const delay = BACKOFF_BASE_MS * Math.pow(2, attempt);
    return Math.min(delay, BACKOFF_MAX_MS);
  }

  /** Clear any pending reconnect timer. Prevents timer stacking. */
  function clearReconnectTimer() {
    if (reconnectTimerId !== null) {
      clearTimeout(reconnectTimerId);
      reconnectTimerId = null;
    }
  }

  /** Build the WebSocket URL per BLUEPRINT.md §15. */
  function buildWsUrl(seq) {
    // Determine WS scheme based on current page protocol
    const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;
    // SECURITY: apiKey is appended as query param per BLUEPRINT.md §17.
    // It is NOT logged here.
    const params = new URLSearchParams({ api_key: apiKey, last_sequence: String(seq) });
    return `${wsScheme}://${host}/ws/tasks/${encodeURIComponent(taskId)}?${params}`;
  }

  /** Parse and validate an incoming WebSocket message. */
  function parseMessage(rawData) {
    if (typeof rawData !== 'string') {
      return { ok: false, reason: 'Non-string message data' };
    }
    let parsed;
    try {
      parsed = JSON.parse(rawData);
    } catch {
      return { ok: false, reason: 'JSON parse failure' };
    }
    if (typeof parsed !== 'object' || parsed === null) {
      return { ok: false, reason: 'Message is not an object' };
    }
    if (!EVENT_FIELDS.every((field) => Object.hasOwn(parsed, field))) {
      return { ok: false, reason: 'Event envelope is missing required fields' };
    }
    if (!Number.isInteger(parsed.sequence) || parsed.sequence < 1) {
      return { ok: false, reason: 'Sequence must be a positive integer' };
    }
    if (parsed.task_id !== taskId || typeof parsed.run_id !== 'string' || typeof parsed.user_id !== 'string') {
      return { ok: false, reason: 'Event identifiers are invalid' };
    }
    if (typeof parsed.event_id !== 'string' || typeof parsed.schema_version !== 'string' || typeof parsed.timestamp !== 'string') {
      return { ok: false, reason: 'Event envelope fields are invalid' };
    }
    if (!EVENT_TYPES.has(parsed.event_type) || !EVENT_STATUSES.has(parsed.status)) {
      return { ok: false, reason: 'Event type or status is invalid' };
    }
    if (typeof parsed.metadata !== 'object' || parsed.metadata === null || Array.isArray(parsed.metadata)) {
      return { ok: false, reason: 'Event metadata must be an object' };
    }
    return { ok: true, envelope: parsed };
  }

  // -------------------------------------------------------------------------
  // Schedule reconnect
  // -------------------------------------------------------------------------

  function scheduleReconnect(delayMs, overflow = false) {
    if (intentionalDisconnect) return;
    if (terminalEventReceived) return;
    if (overflow) {
      overflowReconnectAttempts += 1;
    } else {
      reconnectAttempts += 1;
    }
    if (reconnectAttempts > MAX_RECONNECT_ATTEMPTS || overflowReconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
      emitStatus('failed');
      emitError(
        'WS_MAX_RETRIES',
        `WebSocket reconnection failed after ${MAX_RECONNECT_ATTEMPTS} attempts.`
      );
      return;
    }

    clearReconnectTimer(); // Prevent timer stacking
    emitStatus('reconnecting');

    reconnectTimerId = setTimeout(() => {
      reconnectTimerId = null;
      if (!intentionalDisconnect) {
        connect();
      }
    }, delayMs);
  }

  // -------------------------------------------------------------------------
  // Close existing connection cleanly
  // -------------------------------------------------------------------------

  function closeExisting() {
    if (ws !== null) {
      // Remove all handlers before closing to prevent re-entrant event firing
      ws.onopen    = null;
      ws.onmessage = null;
      ws.onerror   = null;
      ws.onclose   = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(WS_CODE_NORMAL_CLOSURE);
      }
      ws = null;
    }
  }

  // -------------------------------------------------------------------------
  // Connect
  // -------------------------------------------------------------------------

  function connect() {
    if (intentionalDisconnect) return;

    // Prevent multiple simultaneous connections
    closeExisting();

    const url = buildWsUrl(latestSequence);
    emitStatus('connecting');

    let socket;
    try {
      socket = new WebSocket(url);
    } catch (err) {
      emitError('WS_CONNECT_FAILED', 'WebSocket connection could not be created.');
      scheduleReconnect(backoffDelay(reconnectAttempts));
      return;
    }

    ws = socket;

    // ---- onopen ----
    socket.onopen = () => {
      reconnectAttempts = 0; // Reset back-off on successful connection
      emitStatus('connected');
    };

    // ---- onmessage ----
    socket.onmessage = (event) => {
      const result = parseMessage(event.data);

      if (!result.ok) {
        emitError('WS_MALFORMED_MESSAGE', `Discarded malformed message: ${result.reason}`);
        return;
      }

      const { envelope } = result;
      const seq = envelope.sequence;

      // Sequence deduplication — BLUEPRINT.md §16:
      // "Client tracks last_seen_sequence and discards any event where sequence <= last_seen_sequence"
      if (seq <= latestSequence) {
        // Duplicate or stale — silently discard
        return;
      }

      if (seq !== latestSequence + 1) {
        emitError('WS_SEQUENCE_GAP', 'Event sequence gap detected; reconnecting to replay missed events.');
        closeExisting();
        scheduleReconnect(0, true);
        return;
      }

      // Apply the event before advancing the replay cursor.
      try {
        if (onEvent(envelope) === false) {
          emitError('WS_EVENT_NOT_APPLIED', 'Event was not applied; reconnecting to replay it.');
          closeExisting();
          scheduleReconnect(0, true);
          return;
        }
      } catch {
        emitError('WS_EVENT_HANDLER_ERROR', 'Event handler failed; reconnecting to replay it.');
        closeExisting();
        scheduleReconnect(0, true);
        return;
      }

      latestSequence = seq;
      overflowReconnectAttempts = 0;

      if (TERMINAL_EVENTS.has(envelope.event_type)) {
        terminalEventReceived = true;
        clearReconnectTimer();
        closeExisting();
        emitStatus('disconnected');
      }
    };

    // ---- onerror ----
    socket.onerror = () => {
      // WebSocket error events don't carry useful details in browser APIs;
      // the onclose handler fires immediately after and contains the code.
      emitError('WS_ERROR', 'WebSocket connection error.');
    };

    // ---- onclose ----
    socket.onclose = (event) => {
      ws = null;

      if (intentionalDisconnect) {
        emitStatus('disconnected');
        return;
      }
      if (terminalEventReceived) {
        emitStatus('disconnected');
        return;
      }

      const code = event.code;

      if (code === WS_CODE_POLICY_VIOLATION) {
        // Auth failure — do NOT reconnect (BLUEPRINT.md §15 close codes)
        emitStatus('failed');
        emitError(
          'WS_AUTH_FAILURE',
          'WebSocket authentication or task ownership was rejected (1008 Policy Violation).'
        );
        return;
      }

      if (code === WS_CODE_NORMAL_CLOSURE) {
        // Server closed normally — do NOT reconnect
        emitStatus('disconnected');
        return;
      }

      if (code === WS_CODE_TRY_AGAIN_LATER) {
        // Buffer overflow during replay — reconnect quickly with updated last_sequence
        // BLUEPRINT.md §16: "reconnects using its updated last_seen_sequence"
        scheduleReconnect(BACKOFF_1013_MS, true);
        return;
      }

      // All other codes — network drop, server restart, etc.
      scheduleReconnect(backoffDelay(reconnectAttempts));
    };
  }

  // -------------------------------------------------------------------------
  // Start the initial connection
  // -------------------------------------------------------------------------

  connect();

  // -------------------------------------------------------------------------
  // Public handle
  // -------------------------------------------------------------------------

  return {
    /**
     * Perform a clean intentional disconnect.
     * After calling this, the connection will NOT be re-established automatically.
     */
    disconnect() {
      intentionalDisconnect = true;
      clearReconnectTimer();
      closeExisting();
      emitStatus('disconnected');
    },

    /** Return the current highest accepted sequence number. */
    getLatestSequence() {
      return latestSequence;
    },

    /** Return the current connection status string. */
    getStatus() {
      return currentStatus;
    },
  };
}

// ---------------------------------------------------------------------------
// Simplified connect function (matching BLUEPRINT.md §16 code example shape)
// ---------------------------------------------------------------------------

/**
 * Simple WebSocket connector — convenience wrapper matching the BLUEPRINT.md
 * §16 pseudocode shape for teams reading the blueprint directly.
 *
 * @param {string}   taskId
 * @param {string}   apiKey            — Never logged
 * @param {number}   lastSeenSequence
 * @param {function} onEvent
 * @param {function} [onStatusChange]
 * @param {function} [onError]
 * @returns {WsHandle}
 */
export function connectWebSocket(taskId, apiKey, lastSeenSequence, onEvent, onStatusChange, onError) {
  return createWebSocketConnection({
    taskId,
    apiKey,
    initialSequence: lastSeenSequence,
    onEvent,
    onConnectionStatus: onStatusChange ?? (() => {}),
    onError: onError ?? (() => {}),
  });
}
