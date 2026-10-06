import { BrainCircuit, CheckCircle2, ChevronRight, Sparkles } from 'lucide-react'

export default function RecipeBrowser({ recipes = [] }) {
	return (
		<section className="panel recipe-panel" aria-label="Trusted reusable recipes">
			<div className="section-heading">
				<div>
					<span className="eyebrow">REUSABLE KNOWLEDGE</span>
					<h2>Trusted Task Recipes</h2>
				</div>
				<span className="sequence-label">
					<Sparkles size={13} className="text-teal inline mr-1" />
					{recipes.length} verified
				</span>
			</div>

			<div className="recipe-list">
				{recipes.length === 0 ? (
					<div className="empty-state">
						<BrainCircuit size={20} className="text-muted" />
						<p>No trusted recipes stored yet. Complete a task with judge score &ge; 8.5 to promote.</p>
					</div>
				) : (
					recipes.map((recipe) => {
						const id = recipe.recipe_id || recipe.id
						const pattern = recipe.problem_pattern || recipe.pattern
						const strategy = recipe.recommended_strategy || recipe.strategy
						const taskType = recipe.task_type || recipe.taskType || 'general'
						const usageCount = recipe.usage_count ?? recipe.usage ?? 0
						const successCount = recipe.success_after_reuse ?? recipe.success ?? 0

						return (
							<article className="recipe-row" key={id}>
								<div className="recipe-symbol">
									<BrainCircuit size={17} />
								</div>
								<div className="recipe-copy">
									<div className="recipe-title">
										<strong>{pattern}</strong>
										<span className="task-type-badge">{taskType}</span>
									</div>
									<p>{strategy}</p>
									<div className="recipe-meta">
										<span>
											<strong>{usageCount}</strong> retrievals
										</span>
										<span>
											<strong>{successCount}</strong> successful reuses
										</span>
										<span className="vector-badge"><CheckCircle2 size={12} /> Trusted strategy</span>
									</div>
								</div>
								<ChevronRight size={16} className="muted-icon" />
							</article>
						)
					})
				)}
			</div>
		</section>
	)
}
