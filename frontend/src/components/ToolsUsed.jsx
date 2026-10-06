import { Calculator, Code, FileText, Globe } from 'lucide-react'

const TOOL_ICONS = {
	calculator: Calculator,
	file_reader: FileText,
	web_search: Globe,
	code_executor: Code,
}

export default function ToolsUsed({ items = ['calculator'] }) {
	return (
		<div className="tool-list" aria-label="Tools invoked in current run">
			<span className="text-[10px] font-mono text-muted uppercase tracking-wider self-center mr-1">
				Tools In Telemetry:
			</span>
			{items.length === 0 ? (
				<span className="text-muted text-[11px] font-mono">None invoked yet</span>
			) : (
				items.map((tool) => {
					const Icon = TOOL_ICONS[tool] || Calculator
					return (
						<span className="tool-pill" key={tool}>
							<Icon size={13} className="text-teal" />
							<span>{tool.replace(/_/g, ' ')}</span>
						</span>
					)
				})
			)}
		</div>
	)
}
