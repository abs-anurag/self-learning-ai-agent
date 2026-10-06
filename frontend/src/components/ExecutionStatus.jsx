import { CheckCircle2, CircleDot, Clock, Loader2, XCircle } from 'lucide-react'
import StatusBadge from './StatusBadge'

const GRAPH_NODES = [
	{ id: 'understand', label: 'Understand & Retrieve', desc: 'Normalize goal & query memory' },
	{ id: 'plan', label: 'Plan / Replan', desc: 'Synthesize verified steps' },
	{ id: 'execute', label: 'Execute Tools', desc: 'AST Calculator & I/O' },
	{ id: 'evaluate', label: 'Evaluate & Learn', desc: 'Judge & pgvector promotion' },
]

export default function ExecutionStatus({ status = 'pending', iteration = 1, currentStep = '' }) {
	// Active index in graph cycle
	let activeNodeIndex = 0
	if (status === 'pending') {
		activeNodeIndex = 0
	} else if (status === 'running') {
		if (currentStep.toLowerCase().includes('plan')) {
			activeNodeIndex = 1
		} else if (currentStep.toLowerCase().includes('tool') || currentStep.toLowerCase().includes('execut')) {
			activeNodeIndex = 2
		} else if (currentStep.toLowerCase().includes('eval') || currentStep.toLowerCase().includes('learn')) {
			activeNodeIndex = 3
		} else {
			activeNodeIndex = 0
		}
	} else if (status === 'succeeded') {
		activeNodeIndex = 4
	} else if (status === 'failed') {
		activeNodeIndex = 3
	}

	return (
		<section className="panel execution-panel" aria-label="Execution progress and state machine">
			<div className="section-heading">
				<div>
					<span className="eyebrow">GRAPH STATE MACHINE</span>
					<h2>Execution Lifecycle</h2>
				</div>
				<StatusBadge status={status} />
			</div>

			<div className="execution-steps">
				{GRAPH_NODES.map((node, index) => {
					const isDone = status === 'succeeded' || index < activeNodeIndex
					const isCurrent = status === 'running' && index === activeNodeIndex
					const isFailed = status === 'failed' && index === activeNodeIndex

					let Icon = Clock
					if (isDone) Icon = CheckCircle2
					else if (isCurrent) Icon = Loader2
					else if (isFailed) Icon = XCircle

					return (
						<div
							className={`execution-step ${isDone ? 'is-done' : ''} ${isCurrent ? 'is-current' : ''} ${isFailed ? 'is-failed' : ''}`}
							key={node.id}
						>
							<span className="step-icon">
								<Icon size={14} className={isCurrent ? 'animate-spin text-cyan' : ''} />
							</span>
							<div className="step-text">
								<strong>{node.label}</strong>
								<span>{node.desc}</span>
							</div>
						</div>
					)
				})}
			</div>

			<div className="progress-track" aria-hidden="true">
				<span
					style={{
						width:
							status === 'succeeded'
								? '100%'
								: status === 'failed'
									? '100%'
									: status === 'pending'
										? '15%'
										: `${Math.max(25, (activeNodeIndex / 3) * 100)}%`,
					}}
					className={status === 'failed' ? 'bg-coral' : ''}
				/>
			</div>

			<div className="execution-foot">
				<span>
					Iteration <strong>{Math.min(Math.max(iteration, 1), 3)}</strong> of 3 (Cap: 3)
				</span>
				<span>
					Status: <strong className="uppercase">{status}</strong>
				</span>
			</div>
		</section>
	)
}
