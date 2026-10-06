/**
 * Zustand agent telemetry store.
 *
 * Source of truth: BLUEPRINT.md §14, §15, §16, §24.
 *
 * State Architecture:
 * - Unified status vocabulary: 'pending' | 'running' | 'succeeded' | 'failed'
 *   The value 'completed' is NEVER used as a status value (BLUEPRINT §1).
 * - All 11 production event types handled in playMockRun / playRunB / live ingestion
 * - Mock replay player for Day 3 (BLUEPRINT §21, §24)
 * - Live REST + WebSocket integration with FastAPI backend (BLUEPRINT §15, §16)
 *
 * Security:
 * - store NEVER holds chain_of_thought, judge_reasoning, raw prompts,
 *   API keys, secrets, or stack traces (BLUEPRINT §17)
 */

import { create } from 'zustand'
import { taskApi } from '../api/taskApi.js'
import { createWebSocketConnection } from '../api/ws.js'
import { getApiKey } from '../api/http.js'
import {
	mockEvents,
	mockRunBEvents,
	mockMetrics,
	mockRecipes,
	mockTasks,
} from '../mocks/mockEventStream.js'

import {
	INITIAL_VISUALIZATION_STATE,
	reduceVisualizationState,
} from './visualizationState.js'

// Internal event delay between mock stream steps (ms)
const MOCK_STEP_DELAY_MS = 750

// Maximum events kept in the telemetry buffer to bound memory
const MAX_EVENT_BUFFER = 200

/**
 * Normalise errors into a uniform plain serialisable object.
 */
function buildError(err) {
	if (err && err.name === 'ApiError') {
		return {
			code: err.code ?? 'UNKNOWN_ERROR',
			message: err.message ?? 'An error occurred.',
			status: err.status ?? 0,
			requestId: err.requestId ?? '',
		}
	}
	return {
		code: err?.code ?? 'UNKNOWN_ERROR',
		message: err?.message ?? 'An unexpected error occurred.',
		status: err?.status ?? 0,
		requestId: err?.requestId ?? '',
	}
}

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
	const activeTask = state.activeTask || state.currentTask
	if (!activeTask) return { status }

	const taskId = activeTask.task_id || activeTask.id
	const messages = activeTask.messages || [{ role: 'user', content: activeTask.goal }]
	const hasAssistant = messages.some((m) => m.role === 'assistant')
	const updatedMessages = assistantMessage
		? (hasAssistant
			? messages.map((m) => m.role === 'assistant' ? { ...m, content: assistantMessage } : m)
			: [...messages, { role: 'assistant', content: assistantMessage, created_at: new Date().toISOString() }])
		: messages
	const updatedTask = {
		...activeTask,
		messages: updatedMessages,
		status,
		updated_at: new Date().toISOString(),
		...(assistantMessage ? { final_response: assistantMessage } : {}),
	}
	return {
		status,
		activeTask: updatedTask,
		currentTask: updatedTask,
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
	// ─── Core Data State ────────────────────────────────────────────────────
	tasks:          mockTasks,
	recipes:        mockRecipes,
	metrics:        mockMetrics,
	health:         null,

	// Start idle: no events pre-loaded, status pending, empty evaluation
	events:         [],
	latestSequence: 0,
	connectionStatus: 'disconnected',
	reconnecting:   false,
	wsError:        null,

	activeTask:     null,
	currentTask:    null,
	status:         'pending',
	currentStep:    'Autonomous Reasoning Standby — Submit a task or play mock run',
	toolsUsed:      [],
	evaluation:     null,
	candidateRecipe: null,
	learningSaved:  null,
	visualizationState: INITIAL_VISUALIZATION_STATE,

	// Loading & error state slices (for hooks and API calls)
	tasksLoading:       false,
	tasksError:         null,
	tasksPagination:    { page: 1, pageSize: 20, total: 0 },

	taskLoading:        false,
	taskError:          null,

	taskResult:         null,
	taskResultLoading:  false,
	taskResultError:    null,

	recipesLoading:     false,
	recipesError:       null,
	recipesPagination:  { page: 1, pageSize: 20, total: 0 },

	metricsLoading:     false,
	metricsError:       null,

	healthLoading:      false,
	healthError:        null,

	feedbackLoading:    false,
	feedbackError:      null,
	feedbackResult:     null,

	// Playback state
	playback:       { active: false, cursor: 0, mode: 'live' }, // mode: 'live' | 'runA' | 'runB'

	// System state
	systemStatus:   { label: 'METIS Online', state: 'online', sublabel: 'Live backend connected' },
	errorMessage:   null,

	// Internal handles
	_playbackTimeouts: [],
	_liveWsConnection: null,

	// ─── Error Management ────────────────────────────────────────────────────
	setErrorMessage:   (message) => set({ errorMessage: message }),
	clearErrorMessage: () => set({ errorMessage: null }),

	// ─── Chat / Task Navigation ──────────────────────────────────────────────
	startNewChat: () => {
		const { _playbackTimeouts, _liveWsConnection } = get()
		_playbackTimeouts.forEach((id) => window.clearTimeout(id))
		if (_liveWsConnection) {
			_liveWsConnection.disconnect()
		}
		set({
			activeTask: null,
			currentTask: null,
			status: 'pending',
			currentStep: 'Autonomous Reasoning Standby — Submit a task or play mock run',
			events: [],
			latestSequence: 0,
			connectionStatus: 'disconnected',
			reconnecting: false,
			wsError: null,
			toolsUsed: [],
			evaluation: null,
			candidateRecipe: null,
			learningSaved: null,
			visualizationState: INITIAL_VISUALIZATION_STATE,
			playback: { active: false, cursor: 0, mode: 'live' },
			errorMessage: null,
			_playbackTimeouts: [],
			_liveWsConnection: null,
		})
	},

	setActiveTask: (task) => {
		const safeTask = task && typeof task === 'object' ? task : null
		if (!safeTask) {
			get().startNewChat()
			return
		}
		const { _playbackTimeouts, _liveWsConnection } = get()
		_playbackTimeouts.forEach((id) => window.clearTimeout(id))
		if (_liveWsConnection) {
			_liveWsConnection.disconnect()
		}
		const normalizedStatus = safeTask?.status || 'pending'
		const taskId = safeTask.task_id || safeTask.id

		// Ensure messages structure exists
		const messages = Array.isArray(safeTask.messages)
			? safeTask.messages
			: (safeTask.goal ? [{ role: 'user', content: safeTask.goal, created_at: safeTask.created_at || new Date().toISOString() }] : [])

		const taskWithMessages = {
			...safeTask,
			task_id: taskId,
			id: taskId,
			messages,
		}

		set({
			activeTask:   taskWithMessages,
			currentTask:  taskWithMessages,
			status:       normalizedStatus,
			events:       [],
			latestSequence: 0,
			connectionStatus: 'disconnected',
			reconnecting: false,
			wsError:      null,
			toolsUsed:    [],
			playback:     { active: false, cursor: 0, mode: 'live' },
			_playbackTimeouts: [],
			_liveWsConnection: null,
			currentStep:  normalizedStatus === 'succeeded'
				? 'Task execution completed — viewing results'
				: normalizedStatus === 'failed'
					? 'Task ended in a failed state — reviewing outcome'
					: safeTask?.goal
						? 'Task in progress'
						: 'No active task selected',
			evaluation:   null,
			candidateRecipe: null,
			learningSaved: null,
			visualizationState: INITIAL_VISUALIZATION_STATE,
			errorMessage: null,
		})

		// If task is completed, fetch result to populate final response if missing
		if (taskId && normalizedStatus === 'succeeded' && !messages.some(m => m.role === 'assistant')) {
			get().fetchTaskResult(taskId).then((res) => {
				if (res?.final_response) {
					const cur = get()
					const curActive = cur.activeTask
					if (curActive && (curActive.task_id === taskId || curActive.id === taskId)) {
						const updatedTask = {
							...curActive,
							final_response: res.final_response,
							messages: [
								...curActive.messages,
								{ role: 'assistant', content: res.final_response, created_at: new Date().toISOString() },
							],
						}
						set({
							activeTask: updatedTask,
							currentTask: updatedTask,
						})
					}
				}
			}).catch(() => {})
		}
	},

	setCurrentTask: (task) => {
		set({ currentTask: task, activeTask: task })
	},

	clearCurrentTask: () => {
		set({ currentTask: null, activeTask: null })
	},

	continueTask: (content) => {
		const state = get()
		const message = typeof content === 'string' ? content.trim() : ''
		if (!message || state.playback.active || state.status === 'running') return

		// If user was previously running a local demo run mode, continue with demo playback
		if (state.playback.mode === 'runA' || state.playback.mode === 'runB') {
			const activeTask = state.activeTask
			if (!activeTask) return
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
				currentTask: updatedTask,
				tasks: current.tasks.map((task) => (task.task_id || task.id) === taskId ? updatedTask : task),
				status: 'pending',
				currentStep: 'Follow-up added to this conversation',
				events: [],
				latestSequence: 0,
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
			return
		}

		// Real backend task: submit a new task goal to the backend
		get().submitTask(message)
	},

	// ─── Mock Playback System ────────────────────────────────────────────────
	stopMockRun: () => {
		const { _playbackTimeouts } = get()
		_playbackTimeouts.forEach((id) => window.clearTimeout(id))
		set({
			playback:          { active: false, cursor: 0, mode: get().playback.mode },
			_playbackTimeouts: [],
		})
	},

	playMockRun: () => {
		const state = get()
		if (state.playback.active) return

		state._playbackTimeouts.forEach((id) => window.clearTimeout(id))

		set({
			playback:          { active: true, cursor: 0, mode: 'runA' },
			events:            [],
			latestSequence:    0,
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
				const nextEvents = [...currentEvents, event].slice(-MAX_EVENT_BUFFER)

				const updates = {
					events:  nextEvents,
					latestSequence: event.sequence,
					status:  event.status,
					visualizationState: reduceVisualizationState(get().visualizationState, event),
					playback: {
						active:  index < mockEvents.length - 1,
						cursor:  index + 1,
						mode:    'runA',
					},
					currentStep: resolveStepFromEvent(event),
				}

				switch (event.event_type) {
					case 'tool_started':
					case 'tool_completed': {
						const toolName = event.metadata?.tool_name
						if (toolName) {
							updates.toolsUsed = Array.from(new Set([...get().toolsUsed, toolName]))
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

	playRunB: () => {
		const state = get()
		if (state.playback.active) return

		state._playbackTimeouts.forEach((id) => window.clearTimeout(id))

		set({
			playback:          { active: true, cursor: 0, mode: 'runB' },
			events:            [],
			latestSequence:    0,
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
					latestSequence: event.sequence,
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
							updates.toolsUsed = Array.from(new Set([...get().toolsUsed, toolName]))
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

	submitMockTask: (goal) => {
		const taskId = `tsk-${Math.random().toString(36).substring(2, 10)}`
		const runId  = `run-${Math.random().toString(36).substring(2, 10)}`

		const newTask = {
			task_id:    taskId,
			id:         taskId,
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
			currentTask: newTask,
			status:      'pending',
			currentStep: 'Task queued in Celery broker — awaiting worker pickup...',
			events:      [],
			latestSequence: 0,
			visualizationState: INITIAL_VISUALIZATION_STATE,
		}))

		const timeoutId = window.setTimeout(() => {
			get().playMockRun()
		}, 600)
		set((state) => ({ _playbackTimeouts: [...state._playbackTimeouts, timeoutId] }))
	},

	// ─── Event & WebSocket Integration ──────────────────────────────────────
	receiveEvent: (envelope) => {
		const seq = envelope?.sequence
		if (!Number.isInteger(seq) || seq < 1) return false

		const current = get()
		if (seq <= current.latestSequence || seq !== current.latestSequence + 1) return false

		get()._ingestLiveEvent(envelope)
		return true
	},

	setConnectionStatus: (status) => {
		set({ connectionStatus: status, reconnecting: status === 'reconnecting' })
	},

	setReconnecting: (reconnecting) => {
		set({ reconnecting })
	},

	setWsError: (error) => {
		set({ wsError: error })
	},

	clearEvents: () => {
		set({
			events: [],
			latestSequence: 0,
			connectionStatus: 'disconnected',
			reconnecting: false,
			wsError: null,
		})
	},

	connectLiveWebSocket: (taskId, apiKey) => {
		if (get()._liveWsConnection) {
			get()._liveWsConnection.disconnect()
			set({ _liveWsConnection: null })
		}

		const resolvedKey = apiKey || getApiKey()
		if (!resolvedKey) {
			set({
				connectionStatus: 'failed',
				wsError: {
					code: 'MISSING_API_KEY',
					message: 'WebSocket authentication is unavailable. Configure the API key before connecting.',
				},
			})
			return null
		}

		const conn = createWebSocketConnection({
			taskId,
			apiKey: resolvedKey,
			initialSequence: get().latestSequence || 0,
			onEvent: (event) => {
				return get().receiveEvent(event)
			},
			onConnectionStatus: (connStatus) => {
				get().setConnectionStatus(connStatus)
			},
			onError: (err) => {
				get().setWsError(err)
			},
		})

		set({ _liveWsConnection: conn })
		return conn
	},

	disconnectLiveWebSocket: () => {
		if (get()._liveWsConnection) {
			get()._liveWsConnection.disconnect()
			set({ _liveWsConnection: null, connectionStatus: 'disconnected', reconnecting: false })
		}
	},

	_ingestLiveEvent: (event) => {
		if (!event) return

		const currentEvents = get().events
		const nextEvents = [...currentEvents, event].slice(-MAX_EVENT_BUFFER)
		const visualizationState = reduceVisualizationState(get().visualizationState, event)

		const taskStatus = {
			task_started: 'running',
			task_completed: 'succeeded',
			task_failed: 'failed',
		}[event.event_type] ?? null

		const updates = {
			events: nextEvents,
			latestSequence: event.sequence,
			status: visualizationState.terminal.status === 'pending'
				? (taskStatus || event.status || get().status)
				: visualizationState.terminal.status,
			visualizationState,
			currentStep: resolveStepFromEvent(event),
		}

		const currentTask = get().currentTask
		const activeTask = get().activeTask
		const targetId = event.task_id

		if (taskStatus) {
			if (currentTask && (currentTask.task_id === targetId || currentTask.id === targetId)) {
				updates.currentTask = {
					...currentTask,
					status: taskStatus,
					updated_at: event.timestamp || new Date().toISOString(),
				}
			}
			if (activeTask && (activeTask.task_id === targetId || activeTask.id === targetId)) {
				updates.activeTask = {
					...activeTask,
					status: taskStatus,
					updated_at: event.timestamp || new Date().toISOString(),
				}
			}
			updates.tasks = get().tasks.map((task) =>
				(task.task_id === targetId || task.id === targetId)
					? { ...task, status: taskStatus, updated_at: event.timestamp || new Date().toISOString() }
					: task
			)
		}

		switch (event.event_type) {
			case 'tool_started':
			case 'tool_completed': {
				const toolName = event.metadata?.tool_name
				if (toolName) {
					updates.toolsUsed = Array.from(new Set([...get().toolsUsed, toolName]))
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
				const meta = event.metadata || {}
				const initialReply = meta.final_response || meta.outcome_summary || meta.message || null
				if (initialReply) {
					Object.assign(updates, getActiveTaskStatusUpdates(get(), 'succeeded', initialReply))
				} else {
					Object.assign(updates, getActiveTaskStatusUpdates(get(), 'succeeded'))
				}

				// Fetch authoritative terminal result from backend
				if (event.task_id) {
					get().fetchTaskResult(event.task_id).then((result) => {
						if (result?.final_response) {
							const cur = get()
							const curActive = cur.activeTask || cur.currentTask
							if (curActive && (curActive.task_id === event.task_id || curActive.id === event.task_id)) {
								const msgs = curActive.messages || [{ role: 'user', content: curActive.goal }]
								const hasAssistant = msgs.some((m) => m.role === 'assistant')
								const updatedMsgs = hasAssistant
									? msgs.map((m) => m.role === 'assistant' ? { ...m, content: result.final_response } : m)
									: [...msgs, { role: 'assistant', content: result.final_response, created_at: new Date().toISOString() }]
								const updatedTask = {
									...curActive,
									messages: updatedMsgs,
									status: 'succeeded',
									final_response: result.final_response,
								}
								set({
									activeTask: updatedTask,
									currentTask: updatedTask,
									tasks: cur.tasks.map((t) => (t.task_id === event.task_id || t.id === event.task_id) ? updatedTask : t),
								})
							}
						}
					}).catch(() => {})
				}
				break
			}
			case 'task_failed': {
				const meta = event.metadata || {}
				const errMsg = meta.message || meta.termination_reason || 'Task terminated with failure.'
				Object.assign(updates, getActiveTaskStatusUpdates(get(), 'failed', errMsg))
				updates.errorMessage = errMsg
				if (event.task_id) {
					get().fetchTaskResult(event.task_id).catch(() => {})
				}
				break
			}
			default:
				break
		}

		set(updates)
	},

	// ─── Real Backend Integration Actions ─────────────────────────────────────

	/** Submit a live task: create task via REST and connect WebSocket */
	submitTask: async (goal) => {
		const { _playbackTimeouts, _liveWsConnection } = get()
		_playbackTimeouts.forEach((id) => window.clearTimeout(id))
		if (_liveWsConnection) {
			_liveWsConnection.disconnect()
		}

		set({
			status: 'pending',
			currentStep: 'Submitting task to backend...',
			events: [],
			latestSequence: 0,
			toolsUsed: [],
			evaluation: null,
			candidateRecipe: null,
			learningSaved: null,
			visualizationState: INITIAL_VISUALIZATION_STATE,
			playback: { active: false, cursor: 0, mode: 'live' },
			errorMessage: null,
			_playbackTimeouts: [],
			_liveWsConnection: null,
		})

		try {
			const data = await get().createTask(goal)
			get().connectLiveWebSocket(data.task_id)
			return data
		} catch (err) {
			get().setErrorMessage(err?.message || 'Failed to submit task.')
			throw err
		}
	},

	/** Create a task via POST /tasks */
	createTask: async (goal) => {
		set({ taskLoading: true, taskError: null })
		try {
			const data = await taskApi.createTask(goal)
			const taskStub = {
				task_id: data.task_id,
				id: data.task_id,
				run_id: data.run_id,
				goal,
				messages: [{ role: 'user', content: goal, created_at: new Date().toISOString() }],
				status: 'pending',
				task_type: 'general',
				created_at: new Date().toISOString(),
				updated_at: new Date().toISOString(),
				runs: [{ run_id: data.run_id, status: 'pending', iteration_count: 0 }],
			}
			set((state) => ({
				tasks: [taskStub, ...state.tasks],
				currentTask: taskStub,
				activeTask: taskStub,
				taskLoading: false,
			}))
			return data
		} catch (err) {
			set({ taskLoading: false, taskError: buildError(err) })
			throw err
		}
	},

	/** Fetch paginated tasks via GET /tasks */
	fetchTasks: async (page = 1, pageSize = 20) => {
		set({ tasksLoading: true, tasksError: null })
		try {
			const data = await taskApi.listTasks(page, pageSize)
			set({
				tasks: data.items ?? [],
				tasksPagination: {
					page: data.page ?? page,
					pageSize: data.page_size ?? pageSize,
					total: data.total ?? 0,
				},
				tasksLoading: false,
			})
		} catch (err) {
			set({ tasksLoading: false, tasksError: buildError(err) })
		}
	},

	/** Fetch single task via GET /tasks/{id} */
	fetchTask: async (taskId) => {
		set({ taskLoading: true, taskError: null, currentTask: null, activeTask: null })
		try {
			const data = await taskApi.getTask(taskId)
			set({ currentTask: data, activeTask: data, taskLoading: false })
			return data
		} catch (err) {
			set({ taskLoading: false, taskError: buildError(err) })
			throw err
		}
	},

	/** Fetch task result via GET /tasks/{id}/result */
	fetchTaskResult: async (taskId) => {
		set({ taskResultLoading: true, taskResultError: null, taskResult: null })
		try {
			const data = await taskApi.getTaskResult(taskId)
			if (data?._notComplete) {
				set({ taskResultLoading: false, taskResult: null })
			} else {
				set({ taskResult: data, taskResultLoading: false })
			}
			return data
		} catch (err) {
			set({ taskResultLoading: false, taskResultError: buildError(err) })
			throw err
		}
	},

	clearTaskResult: () => {
		set({ taskResult: null, taskResultError: null })
	},

	/** Fetch trusted recipes via GET /memory/recipes */
	fetchRecipes: async (page = 1, pageSize = 20) => {
		set({ recipesLoading: true, recipesError: null })
		try {
			const data = await taskApi.getRecipes(page, pageSize)
			set({
				recipes: data.items ?? [],
				recipesPagination: {
					page: data.page ?? page,
					pageSize: data.page_size ?? pageSize,
					total: data.total ?? 0,
				},
				recipesLoading: false,
			})
		} catch (err) {
			set({ recipesLoading: false, recipesError: buildError(err) })
		}
	},

	/** Fetch aggregate metrics via GET /metrics */
	fetchMetrics: async () => {
		set({ metricsLoading: true, metricsError: null })
		try {
			const data = await taskApi.getMetrics()
			set({ metrics: data, metricsLoading: false })
		} catch (err) {
			set({ metricsLoading: false, metricsError: buildError(err) })
		}
	},

	/** Fetch service health via GET /health */
	fetchHealth: async () => {
		set({ healthLoading: true, healthError: null })
		try {
			const data = await taskApi.getHealth()
			set({
				health: data,
				healthLoading: false,
				systemStatus: {
					label: 'METIS Online',
					state: 'online',
					sublabel: 'Live backend connected',
				},
			})
		} catch (err) {
			set({ healthLoading: false, healthError: buildError(err) })
		}
	},

	/** Submit user feedback via POST /tasks/{id}/feedback */
	submitFeedback: async (taskId, rating, comment = null) => {
		set({ feedbackLoading: true, feedbackError: null, feedbackResult: null })
		try {
			const data = await taskApi.submitFeedback(taskId, rating, comment)
			set({ feedbackResult: data, feedbackLoading: false })
			return data
		} catch (err) {
			set({ feedbackLoading: false, feedbackError: buildError(err) })
			throw err
		}
	},

	clearFeedback: () => {
		set({ feedbackLoading: false, feedbackError: null, feedbackResult: null })
	},
}))

export default useAgentStore
