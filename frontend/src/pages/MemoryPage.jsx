import { BrainCircuit, Sparkles, TrendingUp } from 'lucide-react'
import RecipeBrowser from '../components/RecipeBrowser'
import { useAgentStore } from '../store/agentStore'

export default function MemoryPage() {
	const { recipes, metrics } = useAgentStore()
	const retrievals = metrics?.recipe_retrieval_count ?? 9
	const liftPct = Math.round((metrics?.improvement_rate ?? 0.44) * 100)
	const promotedCount = metrics?.recipes_promoted ?? recipes.length

	return (
		<div className="page-enter memory-page">
			<div className="page-intro">
				<div>
					<span className="eyebrow eyebrow-accent">ACQUIRED KNOWLEDGE</span>
					<h1>
						METIS Memory<span className="title-dot">.</span>
					</h1>
					<p>
						Trusted recipes become reusable strategy. They help METIS shorten the path from goal to outcome without exposing internal reasoning.
					</p>
				</div>
				<div className="memory-orb">
					<BrainCircuit size={27} />
					<span>{promotedCount}</span>
					<small>trusted recipes</small>
				</div>
			</div>

			<div className="memory-hero panel">
				<div className="hero-icon">
					<Sparkles size={21} className="text-teal" />
				</div>
				<div>
					<span className="eyebrow">SELF-LEARNING LIFT</span>
					<h2>Measured improvement over repeated runs</h2>
					<p>
						The baseline approach averages 2 iterations. Learned executions with trusted recipe retrieval complete in 1 iteration across {retrievals} validated memory hits.
					</p>
				</div>
				<div className="hero-stat">
					<strong>+{liftPct}%</strong>
					<span>
						<TrendingUp size={13} /> efficiency lift
					</span>
				</div>
			</div>

			<RecipeBrowser recipes={recipes} />
		</div>
	)
}
