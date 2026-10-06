/**
 * Zustand agent telemetry store.
 *
 * Source of truth: BLUEPRINT.md §14, §15, §16, §24.
 *
 * State Architecture:
 * - Unified status vocabulary: 'pending' | 'running' | 'succeeded' | 'failed'
 *   The value 'completed' is NEVER used as a status value (BLUEPRINT §1).
 * - All 11 production event types handled in playMockRun / playRunB
 * - Mock replay player for Day 3 (BLUEPRINT §21, §24)
 * - Integration hook stubs for Member 2 (live HTTP + WebSocket)
 *
 * Security:
 * - store NEVER holds chain_of_thought, judge_reasoning, raw prompts,
 *   API keys, secrets, or stack traces (BLUEPRINT §17)
 */

import { create } from 'zustand'
import {
	mockEvents,
	mockRunBEvents,
	mockMetrics,
	mockRecipes,
	mockTasks,
} from '../mocks/mockEventStream'

import {
	INITIAL_VISUALIZATION_STATE,
	reduceVisualizationState,
} from './visualizationState'

// Internal event delay between mock stream steps (ms)
const MOCK_STEP_DELAY_MS = 750

// Maximum events kept in the telemetry buffer to bound memory
const MAX_EVENT_BUFFER = 200

/**
 * Derive a human-readable active step description from a production event.
 * Safe: only reads allowlisted metadata keys.
 */
function resolveStepFromEvent(event) {
	const meta = event.metadata || {}
	switch (event.event_type) {
		case 'task_started':
			return 'Initializing agent runtime — task accepted by LangGraph graph'
		case 'memory_retrieved':
			return meta.hits > 0
				? `Memory bank hit: ${meta.hits} trusted recipe(s) retrieved for task type '${meta.task_type || 'general'}'`
				: 'Memory bank queried — no prior trusted recipe matched this task pattern'
		case 'planning_started':
			return `Synthesizing action plan (Iteration ${meta.iteration || 1})`
		case 'tool_started':
			return `Executing tool: ${meta.tool_name || 'external_tool'} — dispatching via ToolRegistry`
		case 'tool_completed':
			return meta.status === 'failed'
				? `Tool failed: ${meta.tool_name || 'tool'} — error code ${meta.error_code || 'TOOL_ERROR'}`
				: `Tool completed: ${meta.tool_name || 'tool'} in ${meta.duration_ms ?? 0}ms`
		case 'evaluation_completed':
			return `Evaluation completed (Iteration ${meta.iteration_count || 1}) — Judge score: ${meta.judge_score ?? '—'}/10 · Success: ${meta.task_success ? 'YES' : 'NO'}`
		case 'reflection_completed':
			return 'Failure analysis captured — routing execution graph to replan next iteration'
		case 'learning_candidate_created':
			return `Candidate recipe extracted: "${meta.problem_pattern || meta.task_type || 'episode'}" — queuing quality gate`
		case 'learning_saved':
			return 'Quality gate passed (score ≥ 8.5) — recipe promoted to trusted pgvector memory'
		case 'task_completed':
			return 'Task reached terminal state: succeeded — final response ready'
		case 'task_failed':
			return `Task terminated with failure — reason: ${meta.termination_reason || meta.error_code || 'unknown'}`
		default:
			return `Processing event: ${event.event_type || 'unknown'}`
	}
}

function getActiveTaskStatusUpdates(state, status, assistantMessage = null) {
	const activeTask = state.activeTask
	if (!activeTask) return { status }

	const taskId = activeTask.task_id || activeTask.id
	const messages = activeTask.messages || [{ role: 'user', content: activeTask.goal }]
	const updatedMessages = assistantMessage
		? [...messages, { role: 'assistant', content: assistantMessage, created_at: new Date().toISOString() }]
		: messages
	const updatedTask = { ...activeTask, messages: updatedMessages, status, updated_at: new Date().toISOString() }
	return {
		status,
		activeTask: updatedTask,
		tasks: state.tasks.map((task) => (task.task_id || task.id) === taskId ? updatedTask : task),
	}
}

function resolveMockReply(task, event) {
	if (!task) return 'The local demo run completed.'
	const userMessages = (task.messages || []).filter((message) => message.role === 'user')
	if (userMessages.length > 1) {
		return 'The local demo run completed. This frontend demo does not generate a task-specific reply to follow-up messages.'
	}

	const fixtureGoals = [mockEvents, mockRunBEvents].map((events) =>
		events.find((eventItem) => eventItem.event_type === 'task_started')?.metadata?.goal,
	)
	if (fixtureGoals.includes(task.goal) && typeof event.metadata?.final_response === 'string') {
		return event.metadata.final_response
	}

	return 'The local demo run completed. This frontend demo does not generate a task-specific response.'
}

export const useAgentStore = create((set, get) => ({
	// ─── Core State ─────────────────────────────────────────────────────────
	tasks:          mockTasks,
	recipes:        mockRecipes,
	metrics:        mockMetrics,

	// Start idle: no events pre-loaded, status pending, empty evaluation
	// Day 3: user must click Play to stream events (BLUEPRINT §21)
	events:         [],
	activeTask:     null,
	status:         'pending',
	currentStep:    'Autonomous Reasoning Standby — Submit a task or play mock run',
	toolsUsed:      [],
	evaluation:     null,
	candidateRecipe: null,
	learningSaved:  null,
	visualizationState: INITIAL_VISUALIZATION_STATE,

	// Playback state
	playback:       { active: false, cursor: 0, mode: 'runA' }, // mode: 'runA' | 'runB'

	// System state
	systemStatus:   { label: 'METIS ONLINE', state: 'online' },
	errorMessage:   null,

	// Internal: stores active timeout IDs so they can be cancelled
	_playbackTimeouts: [],

	// ─── Error Management ────────────────────────────────────────────────────
	setErrorMessage:   (message) => set({ errorMessage: message }),
	clearErrorMessage: () => set({ errorMessage: null }),

	startNewChat: () => {
		const { _playbackTimeouts } = get()
		_playbackTimeouts.forEach((id) => window.clearTimeout(id))
		set({
			activeTask: null,
			status: 'pending',
			currentStep: 'Autonomous Reasoning Standby — Submit a task or play mock run',
			events: [],
			toolsUsed: [],
			evaluation: null,
			candidateRecipe: null,
			learningSaved: null,
			visualizationState: INITIAL_VISUALIZATION_STATE,
			playback: { active: false, cursor: 0, mode: get().playback.mode },
			errorMessage: null,
			_playbackTimeouts: [],
		})
	},

	// ─── Task Selection ──────────────────────────────────────────────────────
	setActiveTask: (task) => {
		const safeTask = task && typeof task === 'object' ? task : null
		if (!safeTask) {
			get().startNewChat()
			return
		}
		get()._playbackTimeouts.forEach((id) => window.clearTimeout(id))
		const normalizedStatus = safeTask?.status || 'pending'

		set({
			activeTask:   safeTask,
			status:       normalizedStatus,
			events:       [],
			toolsUsed:    [],
			playback:     { active: false, cursor: 0, mode: get().playback.mode },
			_playbackTimeouts: [],
			currentStep:  normalizedStatus === 'succeeded'
				? 'Task execution completed — selecting from history'
				: normalizedStatus === 'failed'
					? 'Task ended in a failed state — reviewing prior outcome'
					: safeTask?.goal
						? 'Processing active iteration'
						: 'No active task selected',
			evaluation:   null,
			candidateRecipe: null,
			learningSaved: null,
			visualizationState: INITIAL_VISUALIZATION_STATE,
			errorMessage: null,
		})
	},

	continueTask: (content) => {
		const state = get()
		const activeTask = state.activeTask
		const message = typeof content === 'string' ? content.trim() : ''
		if (!activeTask || !message || state.playback.active) return

		state._playbackTimeouts.forEach((id) => window.clearTimeout(id))
		const taskId = activeTask.task_id || activeTask.id
		const messages = activeTask.messages || [{ role: 'user', content: activeTask.goal }]
		const updatedTask = {
			...activeTask,
			messages: [...messages, { role: 'user', content: message, created_at: new Date().toISOString() }],
			status: 'pending',
			updated_at: new Date().toISOString(),
		}

		set((current) => ({
			activeTask: updatedTask,
			tasks: current.tasks.map((task) => (task.task_id || task.id) === taskId ? updatedTask : task),
			status: 'pending',
			currentStep: 'Follow-up added to this conversation',
			events: [],
			toolsUsed: [],
			evaluation: null,
			candidateRecipe: null,
			learningSaved: null,
			visualizationState: INITIAL_VISUALIZATION_STATE,
			playback: { active: false, cursor: 0, mode: current.playback.mode },
			errorMessage: null,
			_playbackTimeouts: [],
		}))
		get().playMockRun()
	},

	// ─── Stop Mock Run (cancel all pending timeouts) ─────────────────────────
	stopMockRun: () => {
		const { _playbackTimeouts } = get()
		_playbackTimeouts.forEach((id) => window.clearTimeout(id))
		set({
			playback:          { active: false, cursor: 0, mode: get().playback.mode },
			_playbackTimeouts: [],
		})
	},

	// ─── Play Mock Run (Run A: 2-iteration baseline) ─────────────────────────
	// Replays all 14 events from mockEvents at MOCK_STEP_DELAY_MS intervals.
	// BLUEPRINT §21, §24 Run A.
	playMockRun: () => {
		const state = get()
		if (state.playback.active) return

		// Cancel any orphan timeouts from a previous run
		state._playbackTimeouts.forEach((id) => window.clearTimeout(id))

		// Reset UI to clean running state
		set({
			playback:          { active: true, cursor: 0, mode: 'runA' },
			events:            [],
			...getActiveTaskStatusUpdates(state, 'running'),
			toolsUsed:         [],
			currentStep:       'Initializing Run A — baseline execution (no prior recipe)',
			evaluation:        null,
			candidateRecipe:   null,
			learningSaved:     null,
			errorMessage:      null,
			visualizationState: INITIAL_VISUALIZATION_STATE,
			_playbackTimeouts: [],
		})

		const timeouts = []
		mockEvents.forEach((event, index) => {
			const id = window.setTimeout(() => {
				const currentEvents = get().events
				// Enforce buffer cap
				const nextEvents = [...currentEvents, event].slice(-MAX_EVENT_BUFFER)

				const updates = {
					events:  nextEvents,
					status:  event.status,
					visualizationState: reduceVisualizationState(get().visualizationState, event),
					playback: {
						active:  index < mockEvents.length - 1,
						cursor:  index + 1,
						mode:    'runA',
					},
					currentStep: resolveStepFromEvent(event),
				}

				// Derive richer state updates from specific event types
				switch (event.event_type) {
					case 'tool_started':
					case 'tool_completed': {
						const toolName = event.metadata?.tool_name
						if (toolName) {
							updates.toolsUsed = Array.from(
								new Set([...get().toolsUsed, toolName])
							)
						}
						break
					}
					case 'evaluation_completed': {
						const meta = event.metadata || {}
						updates.evaluation = {
							task_success:       meta.task_success       ?? false,
							deterministic_pass: meta.deterministic_pass ?? false,
							tool_success:       meta.tool_success       ?? false,
							judge_score:        meta.judge_score        ?? 0,
							iteration_count:    meta.iteration_count    ?? 1,
							tool_call_count:    meta.tool_call_count    ?? 0,
						}
						break
					}
					case 'learning_candidate_created': {
						const meta = event.metadata || {}
						updates.candidateRecipe = {
							task_type:            meta.task_type,
							problem_pattern:      meta.problem_pattern,
							recommended_strategy: meta.recommended_strategy,
							evaluation_score:     meta.evaluation_score,
						}
						break
					}
					case 'learning_saved': {
						const meta = event.metadata || {}
						updates.learningSaved = {
							recipe_id:         meta.recipe_id,
							learning_decision: meta.learning_decision,
							status:            'trusted',
						}
						break
					}
					case 'task_completed': {
						Object.assign(updates, getActiveTaskStatusUpdates(get(), 'succeeded', resolveMockReply(get().activeTask, event)))
						break
					}
					case 'task_failed': {
						const meta = event.metadata || {}
						Object.assign(updates, getActiveTaskStatusUpdates(get(), 'failed', 'The local demo run could not complete this request.'))
						updates.errorMessage = meta.message || 'Task terminated with failure.'
						break
					}
					default:
						break
				}

				set(updates)
			}, (index + 1) * MOCK_STEP_DELAY_MS)

			timeouts.push(id)
		})

		set({ _playbackTimeouts: timeouts })
	},

	// ─── Play Run B (recipe-retrieved learned run) ───────────────────────────
	// BLUEPRINT §24 Run B: 7 events, 1 iteration, 1 tool call, 50% reduction.
	playRunB: () => {
		const state = get()
		if (state.playback.active) return

		// Cancel any orphan timeouts
		state._playbackTimeouts.forEach((id) => window.clearTimeout(id))

		set({
			playback:          { active: true, cursor: 0, mode: 'runB' },
			events:            [],
			...getActiveTaskStatusUpdates(state, 'running'),
			toolsUsed:         [],
			currentStep:       'Initializing Run B — learned execution (recipe retrieval active)',
			evaluation:        null,
			candidateRecipe:   null,
			learningSaved:     null,
			errorMessage:      null,
			visualizationState: INITIAL_VISUALIZATION_STATE,
			_playbackTimeouts: [],
		})

		const timeouts = []
		mockRunBEvents.forEach((event, index) => {
			const id = window.setTimeout(() => {
				const currentEvents = get().events
				const nextEvents = [...currentEvents, event].slice(-MAX_EVENT_BUFFER)

				const updates = {
					events:  nextEvents,
					status:  event.status,
					visualizationState: reduceVisualizationState(get().visualizationState, event),
					playback: {
						active:  index < mockRunBEvents.length - 1,
						cursor:  index + 1,
						mode:    'runB',
					},
					currentStep: resolveStepFromEvent(event),
				}

				switch (event.event_type) {
					case 'tool_started':
					case 'tool_completed': {
						const toolName = event.metadata?.tool_name
						if (toolName) {
							updates.toolsUsed = Array.from(
								new Set([...get().toolsUsed, toolName])
							)
						}
						break
					}
					case 'evaluation_completed': {
						const meta = event.metadata || {}
						updates.evaluation = {
							task_success:       meta.task_success       ?? false,
							deterministic_pass: meta.deterministic_pass ?? false,
							tool_success:       meta.tool_success       ?? false,
							judge_score:        meta.judge_score        ?? 0,
							iteration_count:    meta.iteration_count    ?? 1,
							tool_call_count:    meta.tool_call_count    ?? 0,
						}
						break
					}
					case 'task_completed': {
						Object.assign(updates, getActiveTaskStatusUpdates(get(), 'succeeded', resolveMockReply(get().activeTask, event)))
						break
					}
					case 'task_failed': {
						const meta = event.metadata || {}
						Object.assign(updates, getActiveTaskStatusUpdates(get(), 'failed', 'The local demo run could not complete this request.'))
						updates.errorMessage = meta.message || 'Task terminated with failure.'
						break
					}
					default:
						break
				}

				set(updates)
			}, (index + 1) * MOCK_STEP_DELAY_MS)

			timeouts.push(id)
		})

		set({ _playbackTimeouts: timeouts })
	},

	// ─── Submit Mock Task (Day 3 — triggers Run A) ───────────────────────────
	submitMockTask: (goal) => {
		const taskId = `tsk-${Math.random().toString(36).substring(2, 10)}`
		const runId  = `run-${Math.random().toString(36).substring(2, 10)}`

		const newTask = {
			task_id:    taskId,
			goal,
			messages:   [{ role: 'user', content: goal, created_at: new Date().toISOString() }],
			status:     'pending',
			task_type:  'mixed',
			created_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
			runs: [
				{
					run_id:             runId,
					status:             'pending',
					termination_reason: null,
					iteration_count:    0,
					created_at:         new Date().toISOString(),
				},
			],
		}

		set((state) => ({
			tasks:       [newTask, ...state.tasks],
			activeTask:  newTask,
			status:      'pending',
			currentStep: 'Task queued in Celery broker — awaiting worker pickup...',
			events:      [],
			visualizationState: INITIAL_VISUALIZATION_STATE,
		}))

		// Simulate Celery worker pickup delay, then play mock stream
		const timeoutId = window.setTimeout(() => {
			get().playMockRun()
		}, 600)
		set((state) => ({ _playbackTimeouts: [...state._playbackTimeouts, timeoutId] }))
	},

	// ─── Member 2 Integration Hooks ──────────────────────────────────────────
	// These are called by Member 2 to connect to the live FastAPI backend.
	// Member 1 owns the state shape; Member 2 owns the network implementation.

	/** Connect POST /tasks → create live task and start WS stream */
	submitTask: async (/* goal */) => {
		/* Member 2: POST /tasks with { goal }, receive { task_id, run_id, status: 'pending' } */
		/* Then call connectLiveWebSocket(task_id, apiKey) */
	},

	/** Fetch GET /tasks for history sidebar */
	fetchTasks: async () => {
		/* Member 2: GET /tasks?page=1&page_size=20, merge into tasks[] */
	},

	/** Fetch GET /memory/recipes for recipe browser */
	fetchRecipes: async () => {
		/* Member 2: GET /memory/recipes?page=1&page_size=20, set recipes[] */
	},

	/** Fetch GET /metrics for the KPI ribbon */
	fetchMetrics: async () => {
		/* Member 2: GET /metrics, set metrics{} */
	},

	/**
	 * Connect to live WebSocket for a task.
	 * ws.js implements the full subscribe-then-replay, 1013 reconnect, dedup.
	 * This hook wires incoming events into the store's dispatch pipeline.
	 */
	connectLiveWebSocket: (/* taskId, apiKey */) => {
		/* Member 2:
		 *   import { connectWebSocket } from '../api/ws'
		 *   const conn = connectWebSocket({
		 *     taskId,
		 *     apiKey,
		 *     initialSequence: get()._lastSeenSequence || 0,
		 *     onEvent: (event) => get()._ingestLiveEvent(event),
		 *     onError: (err) => get().setErrorMessage('WebSocket error'),
		 *     onClose: () => {},
		 *   })
		 */
	},

	/**
	 * Internal: ingest a live event from WebSocket into store state.
	 * Applies same logic as playMockRun without timing delays.
	 * Member 2 calls this via onEvent callback.
	 */
	_ingestLiveEvent: (event) => {
		if (!event || event.sequence <= (get().visualizationState.lastSequence || 0)) return

		const nextEvents = [...get().events, event].slice(-MAX_EVENT_BUFFER)
		const visualizationState = reduceVisualizationState(get().visualizationState, event)
		const updates = {
			events: nextEvents,
			status: visualizationState.terminal.status === 'pending'
				? event.status
				: visualizationState.terminal.status,
			visualizationState,
			currentStep: resolveStepFromEvent(event),
		}

		if (event.event_type === 'task_completed') {
			const response = typeof event.metadata?.final_response === 'string'
				? event.metadata.final_response
				: 'The task completed, but no user-facing response was provided.'
			Object.assign(updates, getActiveTaskStatusUpdates(get(), 'succeeded', response))
		} else if (event.event_type === 'task_failed') {
			Object.assign(updates, getActiveTaskStatusUpdates(get(), 'failed', 'The task could not be completed.'))
		}

		set(updates)
	},
}))
