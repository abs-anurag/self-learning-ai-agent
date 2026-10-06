import { Activity, Award, BrainCircuit, CheckCircle2, Gauge, TrendingUp, Zap } from 'lucide-react'
import MetricCard from './MetricCard'

export default function MetricsDash({ metrics }) {
	const data = metrics || {
		total_tasks: 0,
		successful_tasks: 0,
		failed_tasks: 0,
		success_rate: 0.0,
		average_iterations: 0.0,
		average_tool_calls: 0.0,
		recipes_promoted: 0,
		recipe_retrieval_count: 0,
		successful_reuses: 0,
		average_judge_score: 0.0,
		improvement_rate: 0.0,
	}

	const successRatePct = Math.round((data.success_rate || 0) * 100)
	const improvementPct = Math.round((data.improvement_rate || 0) * 100)

	return (
		<section className="metrics-section" aria-label="System telemetry metrics">
			<div className="section-heading">
				<div>
					<span className="eyebrow">CLOSED-LOOP ANALYTICS</span>
					<h2>Workspace Telemetry & Self-Learning Lift</h2>
				</div>
				<span className="muted-caption">
					<TrendingUp size={14} className="text-teal" />
					Deterministic Golden Metric Delta
				</span>
			</div>

			<div className="metric-grid">
				<MetricCard
					label="Tasks Succeeded"
					value={data.successful_tasks}
					change={12}
					note={`${data.total_tasks} total tasks submitted`}
					icon={CheckCircle2}
					accent="teal"
				/>

				<MetricCard
					label="Success Rate"
					value={`${successRatePct}%`}
					change={4.5}
					note={`${data.failed_tasks} failed runs (bounded)`}
					icon={Gauge}
					accent="coral"
				/>

				<MetricCard
					label="Avg. Iterations"
					value={data.average_iterations.toFixed(1)}
					change={-50}
					note="Run A (2) → Run B (1) lift"
					icon={Activity}
					accent="amber"
				/>

				<MetricCard
					label="Learning Lift"
					value={`+${improvementPct}%`}
					change={improvementPct}
					note={`${data.recipes_promoted} trusted recipes in pgvector`}
					icon={BrainCircuit}
					accent="violet"
				/>
			</div>
		</section>
	)
}
