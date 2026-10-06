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
])

const EVENT_SUBSYSTEMS = {
	task_started: 'PERCEPTION',
	planning_started: 'PERCEPTION',
	memory_retrieved: 'MEMORY_BANK',
	tool_started: 'TOOL_DISPATCH',
	tool_completed: 'TOOL_DISPATCH',
	evaluation_completed: 'EVALUATION_ENGINE',
	reflection_completed: 'REFLECTION',
	learning_candidate_created: 'MEMORY_BANK',
	learning_saved: 'MEMORY_BANK',
	task_completed: 'EVALUATION_ENGINE',
	task_failed: 'REFLECTION',
}

export const INITIAL_VISUALIZATION_STATE = {
	currentNode: 'standby',
	iteration: 0,
	tool: { active: false, name: null, status: 'pending', durationMs: null },
	memory: { active: false, hits: 0, taskType: null, recipeRetrieved: false },
	evaluation: null,
	learning: { phase: 'standby', candidateCreated: false, saved: false },
	terminal: { status: 'pending', reason: null },
	activeSubsystem: 'PERCEPTION',
	lastEventType: null,
	lastSequence: 0,
	eventPulse: 0,
}

function safeToolName(value) {
	return typeof value === 'string' && value.length <= 80 ? value : null
}

function safeStatus(value) {
	return value === 'succeeded' || value === 'failed' || value === 'running' || value === 'pending'
		? value
		: 'pending'
}

function safeNonNegativeNumber(value, fallback = 0) {
	return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback
}

function safeEventType(value) {
	return EVENT_TYPES.has(value) ? value : null
}

export function reduceVisualizationState(state = INITIAL_VISUALIZATION_STATE, event = {}) {
	const eventType = safeEventType(event.event_type)
	if (!eventType) return state

	const meta = event.metadata && typeof event.metadata === 'object' ? event.metadata : {}
	const next = {
		...state,
		activeSubsystem: EVENT_SUBSYSTEMS[eventType],
		lastEventType: eventType,
		lastSequence: safeNonNegativeNumber(event.sequence, state.lastSequence),
		eventPulse: state.eventPulse + 1,
		terminal: { ...state.terminal },
		tool: { ...state.tool },
		memory: { ...state.memory },
		learning: { ...state.learning },
	}

	switch (eventType) {
		case 'task_started':
			next.currentNode = 'understand'
			next.terminal = { status: 'running', reason: null }
			break
		case 'planning_started':
			next.currentNode = 'plan'
			next.iteration = safeNonNegativeNumber(meta.iteration, state.iteration || 1)
			next.terminal = { status: 'running', reason: null }
			break
		case 'memory_retrieved':
			next.currentNode = 'retrieve_memory'
			next.memory = {
				active: true,
				hits: safeNonNegativeNumber(meta.hits),
				taskType: typeof meta.task_type === 'string' ? meta.task_type : null,
				recipeRetrieved: safeNonNegativeNumber(meta.hits) > 0,
			}
			break
		case 'tool_started':
			next.currentNode = 'execute'
			next.tool = {
				active: true,
				name: safeToolName(meta.tool_name),
				status: 'running',
				durationMs: null,
			}
			break
		case 'tool_completed':
			next.currentNode = 'observe'
			next.tool = {
				active: false,
				name: safeToolName(meta.tool_name),
				status: safeStatus(meta.status),
				durationMs: safeNonNegativeNumber(meta.duration_ms, null),
			}
			break
		case 'evaluation_completed':
			next.currentNode = 'evaluate'
			next.iteration = safeNonNegativeNumber(meta.iteration_count, state.iteration || 1)
			next.evaluation = {
				taskSuccess: meta.task_success === true,
				deterministicPass: meta.deterministic_pass === true,
				toolSuccess: meta.tool_success === true,
				judgeScore: typeof meta.judge_score === 'number' ? meta.judge_score : null,
				toolCallCount: safeNonNegativeNumber(meta.tool_call_count),
			}
			break
		case 'reflection_completed':
			next.currentNode = 'reflect'
			break
		case 'learning_candidate_created':
			next.currentNode = 'maybe_learn'
			next.learning = { ...next.learning, phase: 'candidate', candidateCreated: true }
			break
		case 'learning_saved':
			next.currentNode = 'maybe_learn'
			next.learning = { ...next.learning, phase: 'saved', saved: true }
			break
		case 'task_completed':
			next.currentNode = 'respond'
			next.terminal = { status: 'succeeded', reason: null }
			break
		case 'task_failed':
			next.currentNode = 'respond'
			next.terminal = {
				status: 'failed',
				reason: typeof meta.termination_reason === 'string' ? meta.termination_reason : null,
			}
			break
		default:
			break
	}

	return next
}

export function deriveVisualizationState(events = []) {
	return events.reduce(reduceVisualizationState, INITIAL_VISUALIZATION_STATE)
}
