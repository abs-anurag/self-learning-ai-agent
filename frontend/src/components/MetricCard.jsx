import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'

export default function MetricCard({ label, value, change, note, icon: Icon, accent = 'teal' }) {
	const Trend = change > 0 ? ArrowUpRight : change < 0 ? ArrowDownRight : Minus

	return (
		<article className={`metric-card metric-card--${accent}`}>
			<div className="metric-card-top">
				<span className="metric-label">{label}</span>
				<span className="metric-icon">
					<Icon size={17} />
				</span>
			</div>
			<div className="metric-value">{value}</div>
			<div className="metric-foot">
				<span
					className={`metric-change ${change > 0 ? 'positive' : change < 0 ? 'negative' : ''}`}
				>
					<Trend size={14} />
					{change === 0 ? 'Stable' : `${Math.abs(change)}%`}
				</span>
				<span>{note}</span>
			</div>
		</article>
	)
}