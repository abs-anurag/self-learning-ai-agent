import { Activity, BrainCircuit, CheckCircle2, CircleDot, Database, GitBranch, Loader2, ShieldCheck, Sparkles, Wrench, XCircle } from 'lucide-react'

const GRAPH_NODES = [
	{ id: 'understand', label: 'Understand', short: 'INTAKE', icon: CircleDot, position: [10, 50] },
	{ id: 'plan', label: 'Plan', short: 'PLAN', icon: GitBranch, position: [23, 24] },
	{ id: 'retrieve_memory', label: 'Memory', short: 'MEMORY', icon: Database, position: [42, 17] },
	{ id: 'execute', label: 'Tools', short: 'TOOLS', icon: Wrench, position: [62, 24] },
	{ id: 'observe', label: 'Observe', short: 'OBSERVE', icon: Activity, position: [82, 50] },
	{ id: 'evaluate', label: 'Evaluate', short: 'EVALUATE', icon: ShieldCheck, position: [62, 76] },
	{ id: 'reflect', label: 'Reflect', short: 'REFLECT', icon: GitBranch, position: [42, 83] },
	{ id: 'maybe_learn', label: 'Learn', short: 'LEARN', icon: BrainCircuit, position: [23, 76] },
	{ id: 'respond', label: 'Respond', short: 'RESULT', icon: CheckCircle2, position: [90, 15] },
]

const GRAPH_EDGES = [
	['understand', 'plan'],
	['plan', 'retrieve_memory'],
	['retrieve_memory', 'execute'],
	['execute', 'observe'],
	['observe', 'evaluate'],
	['evaluate', 'reflect'],
	['reflect', 'maybe_learn'],
	['maybe_learn', 'execute'],
	['evaluate', 'respond'],
	['maybe_learn', 'respond'],
]

const ACTIVE_SUBSYSTEM_LABELS = {
	PERCEPTION: 'Planning subsystem',
	MEMORY_BANK: 'Memory subsystem',
	TOOL_DISPATCH: 'Tool dispatch',
	EVALUATION_ENGINE: 'Evaluation engine',
	REFLECTION: 'Reflection loop',
}

function nodeIsActive(node, visualState) {
	return node.id === visualState.currentNode || (
		visualState.learning.saved && node.id === 'maybe_learn'
	)
}

function nodeIsComplete(node, visualState) {
	const activeIndex = GRAPH_NODES.findIndex((item) => item.id === visualState.currentNode)
	const nodeIndex = GRAPH_NODES.findIndex((item) => item.id === node.id)
	return activeIndex > -1 && nodeIndex > -1 && nodeIndex < activeIndex
}

function getStatusLabel(status, visualState) {
	if (status === 'succeeded') return 'SUCCESS'
	if (status === 'failed') return 'FAILURE'
	if (visualState.lastEventType) return visualState.lastEventType.replace(/_/g, ' ').toUpperCase()
	return 'IDLE'
}

export default function AgentGraph2D({ status = 'pending', visualState }) {
	const state = visualState || {
		currentNode: 'standby',
		iteration: 0,
		tool: { active: false, name: null },
		memory: { active: false, hits: 0 },
		evaluation: null,
		learning: { phase: 'standby', saved: false },
		terminal: { status },
		activeSubsystem: 'PERCEPTION',
		lastEventType: null,
		lastSequence: 0,
	}
	const statusLabel = getStatusLabel(status, state)
	const isTerminal = status === 'succeeded' || status === 'failed'
	const visualMode = isTerminal ? status : state.currentNode === 'standby' ? 'idle' : state.activeSubsystem.toLowerCase()

	return (
		<section className={`agent-graph panel agent-graph--${visualMode}`} aria-label="2D agent execution graph">
			<div className="agent-graph-heading">
				<div>
					<span className="eyebrow">AGENT ACTIVITY GRAPH</span>
					<h2>Execution topology</h2>
				</div>
				<div className="agent-graph-status">
					<span className="agent-graph-status-dot" />
					<span>{statusLabel}</span>
				</div>
			</div>

			<div className="agent-graph-canvas">
				<svg viewBox="0 0 100 100" role="img" aria-labelledby="agent-graph-title agent-graph-description">
					<title id="agent-graph-title">Agent execution stages</title>
					<desc id="agent-graph-description">A safe visual map of documented agent stages and their current telemetry state.</desc>
					<defs>
						<linearGradient id="graph-line" x1="0" x2="1">
							<stop offset="0" stopColor="currentColor" stopOpacity="0.16" />
							<stop offset="0.5" stopColor="currentColor" stopOpacity="0.8" />
							<stop offset="1" stopColor="currentColor" stopOpacity="0.16" />
						</linearGradient>
					</defs>
					{GRAPH_EDGES.map(([fromId, toId]) => {
						const from = GRAPH_NODES.find((node) => node.id === fromId)
						const to = GRAPH_NODES.find((node) => node.id === toId)
						const isActive = fromId === state.currentNode || toId === state.currentNode || state.learning.saved
						return (
							<line
								key={`${fromId}-${toId}`}
								x1={from.position[0]}
								y1={from.position[1]}
								x2={to.position[0]}
								y2={to.position[1]}
								className={`agent-graph-edge ${isActive ? 'agent-graph-edge--active' : ''}`}
								pathLength="1"
							/>
						)
					})}
					<circle cx="50" cy="50" r="10" className="agent-graph-core" />
					<circle cx="50" cy="50" r="5" className="agent-graph-core-inner" />
					<text x="50" y="49" textAnchor="middle" className="agent-graph-core-label">METIS</text>
					<text x="50" y="54" textAnchor="middle" className="agent-graph-core-subtitle">AGENT CORE</text>
					{GRAPH_NODES.map((node) => {
						const Icon = node.icon
						const active = nodeIsActive(node, state)
						const complete = nodeIsComplete(node, state)
						return (
							<g key={node.id} className={`agent-graph-node ${active ? 'agent-graph-node--active' : ''} ${complete ? 'agent-graph-node--complete' : ''}`} transform={`translate(${node.position[0]} ${node.position[1]})`}>
								<circle r="7" className="agent-graph-node-halo" />
								<circle r="5.5" className="agent-graph-node-disc" />
								<foreignObject x="-3.5" y="-3.5" width="7" height="7">
									<div className="agent-graph-node-icon"><Icon size={11} /></div>
								</foreignObject>
								<text y="10" textAnchor="middle" className="agent-graph-node-label">{node.short}</text>
							</g>
						)
					})}
				</svg>

				<div className="agent-graph-readout">
					<span><strong>NODE</strong> {state.currentNode.replace(/_/g, ' ')}</span>
					<span><strong>ITER</strong> {state.iteration || 0}/3</span>
					<span><strong>SEQ</strong> #{String(state.lastSequence || 0).padStart(3, '0')}</span>
				</div>
			</div>

			<div className="agent-graph-footer">
				<span>{ACTIVE_SUBSYSTEM_LABELS[state.activeSubsystem] || 'Agent standby'}</span>
				<span>{state.tool.active ? `Tool active: ${state.tool.name || 'dispatch'}` : state.memory.recipeRetrieved ? `${state.memory.hits} memory hit${state.memory.hits === 1 ? '' : 's'}` : state.learning.saved ? 'Trusted recipe saved' : 'Telemetry synchronized'}</span>
			</div>
		</section>
	)
}
