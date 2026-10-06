import { Award, CheckCircle2, Gauge, ShieldCheck, Target, XCircle } from 'lucide-react'

export default function EvaluationPanel({ evaluation, status = 'pending' }) {
	const evalData = evaluation || {
		task_success: false,
		deterministic_pass: false,
		tool_success: false,
		judge_score: 0.0,
		iteration_count: 1,
		tool_call_count: 0,
	}

	const isPromotable = evalData.judge_score >= 8.5 && evalData.task_success
	const isPassed = evalData.task_success

	return (
		<section className="panel evaluation-panel" aria-label="Composite evaluation quality signals">
			<div className="section-heading">
				<div>
					<span className="eyebrow">COMPOSITE EVALUATOR</span>
					<h2>Quality Signals</h2>
				</div>
				<div className="flex items-center gap-2">
					{isPromotable && (
						<span className="badge-promo" title="Meets >= 8.5 promotion threshold for pgvector storage">
							<Award size={13} className="text-amber" /> Gate Promoted
						</span>
					)}
					<span
						className={`score-ring ${evalData.judge_score >= 8.5 ? 'score-ring--gold' : evalData.judge_score >= 6.0 ? 'score-ring--green' : 'score-ring--dim'}`}
					>
						{evalData.judge_score > 0 ? evalData.judge_score.toFixed(1) : '—'}
					</span>
				</div>
			</div>

			<div className="evaluation-grid">
				<div className={`eval-cell ${evalData.task_success ? 'is-pass' : 'is-fail'}`}>
					<Target size={16} />
					<span>Task success</span>
					<strong>{evalData.task_success ? 'PASSED (>=6.0)' : 'PENDING / FAILED'}</strong>
				</div>

				<div className={`eval-cell ${evalData.deterministic_pass ? 'is-pass' : 'is-fail'}`}>
					<ShieldCheck size={16} />
					<span>Deterministic</span>
					<strong>{evalData.deterministic_pass ? 'VERIFIED' : 'FAILED / UNCHECKED'}</strong>
				</div>

				<div className={`eval-cell ${evalData.tool_success ? 'is-pass' : 'is-fail'}`}>
					<Gauge size={16} />
					<span>Tool success</span>
					<strong>{evalData.tool_success ? '100% OK' : 'TOOL ERROR / RETRY'}</strong>
				</div>

				<div className="eval-cell">
					<CheckCircle2 size={16} />
					<span>Iteration</span>
					<strong>{evalData.iteration_count} of 3</strong>
				</div>
			</div>

			<div className="eval-footer">
				<span>
					Promotion Gate: Judge Score <strong>&ge; 8.5</strong> required for self-learning
				</span>
			</div>
		</section>
	)
}
