import { ArrowUpRight, BrainCircuit, CheckCircle2, Clock, Sparkles } from 'lucide-react'

export default function LearningEvents({ candidate, learningSaved }) {
	const isPromoted = Boolean(learningSaved)
	const hasCandidate = Boolean(candidate)

	return (
		<section className="panel learning-panel" aria-label="Self-learning loop events">
			<div className="section-heading">
				<div>
					<span className="eyebrow">CLOSED SELF-LEARNING LOOP</span>
					<h2>Memory Evolution</h2>
				</div>
				{isPromoted ? (
					<span className="mini-tag mini-tag--promoted">
						<CheckCircle2 size={13} /> Promoted
					</span>
				) : hasCandidate ? (
					<span className="mini-tag mini-tag--candidate">
						<Sparkles size={13} /> Candidate
					</span>
				) : (
					<span className="mini-tag mini-tag--standby">
						<Clock size={13} /> Standing By
					</span>
				)}
			</div>

			{isPromoted ? (
				<>
					<div className="learning-summary">
						<div className="learning-mark learning-mark--emerald">
							<BrainCircuit size={22} />
						</div>
						<div>
							<strong>{candidate?.problem_pattern || 'Compound Interest Strategy'}</strong>
							<p>Passed 7-criteria quality gate. Embedded into pgvector vector space.</p>
						</div>
						<ArrowUpRight size={17} className="muted-icon" />
					</div>
					<div className="learning-stats">
						<span>
							<strong>384-d</strong> MiniLM Vector
						</span>
						<span>
							<strong>Status</strong> Trusted
						</span>
						<span>
							<strong>Strategy</strong> Retrievable
						</span>
					</div>
				</>
			) : hasCandidate ? (
				<>
					<div className="learning-summary">
						<div className="learning-mark learning-mark--amber">
							<Sparkles size={22} />
						</div>
						<div>
							<strong>{candidate.problem_pattern || 'Candidate Strategy Extracted'}</strong>
							<p>{candidate.recommended_strategy || 'Candidate evaluated for promotion gate...'}</p>
						</div>
					</div>
					<div className="learning-stats">
						<span>
							<strong>Score</strong> {candidate.evaluation_score || 9.0}
						</span>
						<span>
							<strong>Status</strong> Candidate Pre-Gate
						</span>
					</div>
				</>
			) : (
				<div className="learning-summary opacity-60">
					<div className="learning-mark">
						<BrainCircuit size={22} />
					</div>
					<div>
						<strong>No active learning event</strong>
						<p>Successful non-trivial task runs automatically trigger candidate extraction and the 8.5 quality gate.</p>
					</div>
				</div>
			)}
		</section>
	)
}
