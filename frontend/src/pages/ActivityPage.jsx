import { lazy, Suspense } from 'react'
import { Activity } from 'lucide-react'
import EvaluationPanel from '../components/EvaluationPanel'
import LearningEvents from '../components/LearningEvents'
import MetricsDash from '../components/MetricsDash'
import SafeActivityFeed from '../components/SafeActivityFeed'
import ToolsUsed from '../components/ToolsUsed'
import { useAgentStore } from '../store/agentStore'

const AgentGraph2D = lazy(() => import('../components/AgentGraph2D'))

export default function ActivityPage() {
	const { metrics, events, status, toolsUsed, evaluation, candidateRecipe, learningSaved, visualizationState } = useAgentStore()
	const lifecycle = [
		{ label: 'Goal', nodes: ['understand'] },
		{ label: 'Plan', nodes: ['plan', 'retrieve_memory'] },
		{ label: 'Tools', nodes: ['execute', 'observe'] },
		{ label: 'Evaluate', nodes: ['evaluate', 'reflect'] },
		{ label: 'Learn', nodes: ['maybe_learn'] },
		{ label: 'Result', nodes: ['respond'] },
	]
	const currentStage = lifecycle.findIndex((stage) => stage.nodes.includes(visualizationState.currentNode))
	const activeStage = status === 'succeeded' ? lifecycle.length - 1 : currentStage < 0 ? 0 : currentStage

	return (
		<div className="activity-page page-enter">
			<div className="page-intro">
				<div>
					<span className="eyebrow eyebrow-accent">AGENT WORKSPACE</span>
					<h1><Activity size={25} /> Activity</h1>
					<p>Execution stages, tools, evaluation, and learning for the current run.</p>
				</div>
				<span className={`status-badge status-badge--${status}`}>{status}</span>
			</div>

			<ol className="lifecycle-ribbon" aria-label="Agent lifecycle">
				{lifecycle.map((stage, index) => (
					<li
						className={`${index < activeStage || status === 'succeeded' ? 'is-complete' : ''} ${index === activeStage ? 'is-active' : ''}`}
						key={stage.label}
					>
						<span>{String(index + 1).padStart(2, '0')}</span>
						<strong>{stage.label}</strong>
					</li>
				))}
			</ol>

			<Suspense fallback={<div className="panel agent-graph-fallback">Loading activity map…</div>}>
				<AgentGraph2D status={status} visualState={visualizationState} />
			</Suspense>

			<ToolsUsed items={toolsUsed} />
			<div className="activity-detail-grid">
				<EvaluationPanel evaluation={evaluation} status={status} />
				<LearningEvents candidate={candidateRecipe} learningSaved={learningSaved} />
			</div>
			<SafeActivityFeed events={events} />
			<MetricsDash metrics={metrics} />
		</div>
	)
}
