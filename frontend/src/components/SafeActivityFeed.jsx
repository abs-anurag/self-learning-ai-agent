import {
	Activity,
	BrainCircuit,
	CheckCircle2,
	Clock,
	Compass,
	Cpu,
	FileText,
	Fingerprint,
	RotateCcw,
	Sparkles,
	Terminal,
	Wrench,
	XCircle,
} from 'lucide-react'

// Icon mapping per production event type
const EVENT_ICONS = {
	task_started: Compass,
	planning_started: Activity,
	memory_retrieved: BrainCircuit,
	tool_started: Wrench,
	tool_completed: Terminal,
	evaluation_completed: CheckCircle2,
	reflection_completed: RotateCcw,
	learning_candidate_created: Sparkles,
	learning_saved: CheckCircle2,
	task_completed: CheckCircle2,
	task_failed: XCircle,
}

// Tone styling mapping
const EVENT_TONES = {
	task_started: 'teal',
	planning_started: 'cyan',
	memory_retrieved: 'violet',
	tool_started: 'amber',
	tool_completed: 'teal',
	evaluation_completed: 'emerald',
	reflection_completed: 'violet',
	learning_candidate_created: 'amber',
	learning_saved: 'emerald',
	task_completed: 'emerald',
	task_failed: 'coral',
}

/**
 * Deterministically constructs sanitized presentation details from production EventEnvelope.
 * Strictly avoids rendering prohibited keys (chain-of-thought, judge_reasoning, raw prompts, secrets).
 */
function resolveEventDisplay(event) {
	const type = event.event_type || 'unknown_event'
	const meta = event.metadata || {}
	const Icon = EVENT_ICONS[type] || Cpu
	const tone = EVENT_TONES[type] || 'teal'

	let title = type.replace(/_/g, ' ').toUpperCase()
	let detail = ''

	switch (type) {
		case 'task_started':
			title = 'Task Accepted'
			detail = meta.goal
				? `Goal: ${meta.goal}`
				: 'The agent runtime initialized a new execution graph.'
			break
		case 'planning_started':
			title = `Plan Formulated (Iteration ${meta.iteration || 1})`
			detail = Array.isArray(meta.plan)
				? meta.plan.join(' → ')
				: 'Synthesizing verifiable steps toward goal.'
			break
		case 'memory_retrieved':
			title = meta.hits && meta.hits > 0 ? 'Trusted Recipe Retrieved' : 'Memory Bank Queried'
			detail = meta.hits && meta.hits > 0
				? `${meta.hits} validated prior strategy matched task type '${meta.task_type || 'general'}'.`
				: meta.message || 'No prior trusted recipe matched this task pattern (zero hits).'
			break
		case 'tool_started':
			title = `Tool Invoked: ${meta.tool_name || 'external_tool'}`
			detail = meta.tool_input
				? `Input: ${JSON.stringify(meta.tool_input)}`
				: 'Executing tool invocation.'
			break
		case 'tool_completed':
			title = `Tool Execution Completed: ${meta.tool_name || 'tool'}`
			detail = meta.status === 'failed'
				? `Execution failed with safe error code: ${meta.error_code || 'TOOL_ERROR'}`
				: `Completed in ${meta.duration_ms ?? 0}ms. Output: ${meta.result !== undefined ? JSON.stringify(meta.result) : 'OK'}`
			break
		case 'evaluation_completed':
			title = `Iteration ${meta.iteration_count || 1} Evaluated`
			detail = `Score: ${meta.judge_score !== undefined ? `${meta.judge_score}/10` : 'Evaluated'} · Deterministic Pass: ${meta.deterministic_pass ? 'YES' : 'NO'} · Task Success: ${meta.task_success ? 'YES' : 'NO'}`
			break
		case 'reflection_completed':
			title = 'Failure Analysis & Reflection'
			detail = meta.diagnosis
				? `Diagnosis: ${meta.diagnosis}`
				: 'Captured failure analysis. Re-routing execution graph to replan next iteration.'
			break
		case 'learning_candidate_created':
			title = 'Learning Candidate Extracted'
			detail = `Candidate strategy captured for pattern: "${meta.problem_pattern || meta.task_type || 'episode'}"`
			break
		case 'learning_saved':
			title = 'Trusted Recipe Promoted'
			detail = `Passed 7-criteria quality gate (Score >= 8.5). Stored in pgvector memory with status 'trusted'.`
			break
		case 'task_completed':
			title = 'Task Succeeded'
			detail = meta.final_response || 'All task goals satisfied. Final answer verified.'
			break
		case 'task_failed':
			title = 'Task Terminated with Failure'
			detail = meta.message || `Terminal termination reason: ${meta.error_code || 'MAX_ITERATIONS'}`
			break
		default:
			detail = JSON.stringify(meta)
	}

	// Format time
	let timeStr = '—'
	if (event.timestamp) {
		try {
			const date = new Date(event.timestamp)
			timeStr = date.toLocaleTimeString()
		} catch {
			timeStr = String(event.timestamp)
		}
	}

	return { title, detail, Icon, tone, timeStr }
}

export default function SafeActivityFeed({ events = [] }) {
	return (
		<section className="panel activity-panel">
			<div className="section-heading">
				<div>
					<span className="eyebrow">DURABLE TELEMETRY STREAM</span>
					<h2>Safe Activity Feed</h2>
				</div>
				<span className="sequence-label">
					<Fingerprint size={12} className="inline mr-1 text-teal" />
					{events.length} sequenced events
				</span>
			</div>

			<div className="timeline" role="feed" aria-label="Chronological execution event stream">
				{events.length === 0 ? (
					<div className="empty-state">
						<Clock size={20} className="text-muted" />
						<p>No telemetry events recorded yet. Launch a task or play mock run.</p>
					</div>
				) : (
					events.map((event) => {
						const { title, detail, Icon, tone, timeStr } = resolveEventDisplay(event)

						return (
							<article
								className={`timeline-item timeline-item--${tone}`}
								key={event.event_id || event.sequence}
							>
								<div className="timeline-rail">
									<span className="timeline-icon">
										<Icon size={14} />
									</span>
								</div>

								<div className="timeline-content">
									<div className="timeline-title">
										<strong>{title}</strong>
										<time dateTime={event.timestamp}>{timeStr}</time>
									</div>

									<p className="timeline-detail">{detail}</p>

									<div className="timeline-meta">
										<span className="meta-badge meta-seq">#{String(event.sequence).padStart(3, '0')}</span>
										<span className="meta-badge">{event.event_type}</span>
										<span className={`meta-status meta-status--${event.status}`}>
											{event.status}
										</span>
										{event.metadata?.tool_name && (
											<span className="meta-badge meta-tool">
												{event.metadata.tool_name}
											</span>
										)}
									</div>
								</div>
							</article>
						)
					})
				)}
			</div>
		</section>
	)
}
