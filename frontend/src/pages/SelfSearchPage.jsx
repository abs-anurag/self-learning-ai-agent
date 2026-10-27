import React, { useState } from 'react'
import {
	AlertCircle,
	AlertTriangle,
	CheckCircle2,
	ChevronDown,
	ChevronUp,
	CornerDownLeft,
	FileSearch,
	FileText,
	HelpCircle,
	Info,
	RotateCcw,
	Search,
	ShieldAlert,
	Sparkles,
	Trash2,
} from 'lucide-react'
import { useSelfSearchStore } from '../store/selfSearchStore'

const MAX_DOC_LENGTH = 100000
const MAX_QUESTION_LENGTH = 2000

export default function SelfSearchPage() {
	const {
		document,
		question,
		answer,
		loading,
		error,
		history,
		setDocument,
		setQuestion,
		clearDocument,
		clearHistory,
		clearError,
		askQuestion,
	} = useSelfSearchStore()

	const [expandedHistoryId, setExpandedHistoryId] = useState(null)
	const [activeTab, setActiveTab] = useState('current') // 'current' | 'history'

	const docLength = document.length
	const qLength = question.length
	const isDocEmpty = !document.trim()
	const isQEmpty = !question.trim()

	const handleSubmit = async (e) => {
		if (e) e.preventDefault()
		if (loading || isDocEmpty || isQEmpty) return
		await askQuestion()
	}

	const handleKeyDown = (e) => {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault()
			handleSubmit()
		}
	}

	const toggleHistoryItem = (id) => {
		setExpandedHistoryId((prev) => (prev === id ? null : id))
	}

	return (
		<div className="page-enter self-search-page" style={{ padding: '0 0 60px 0', maxWidth: '1100px', margin: '0 auto' }}>
			{/* Page Header */}
			<div className="page-intro" style={{ marginBottom: '24px' }}>
				<div>
					<span className="eyebrow eyebrow-accent">GROUNDED DOCUMENT Q&amp;A</span>
					<h1 style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
						Self Search<span className="title-dot">.</span>
					</h1>
					<p style={{ maxWidth: '640px' }}>
						Ask questions directly against your document. Answers are strictly grounded in verified verbatim passages, without hallucination or external knowledge.
					</p>
				</div>
				<div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
					<span
						style={{
							display: 'inline-flex',
							alignItems: 'center',
							gap: '6px',
							fontSize: '12px',
							color: 'var(--soft)',
							background: 'rgba(255, 255, 255, 0.04)',
							padding: '6px 12px',
							borderRadius: '20px',
							border: '1px solid rgba(255, 255, 255, 0.08)',
						}}
					>
						<FileSearch size={14} className="text-teal" />
						In-Memory Context
					</span>
				</div>
			</div>

			{/* Ephemeral Memory Notice */}
			<div
				role="status"
				style={{
					display: 'flex',
					alignItems: 'flex-start',
					gap: '12px',
					padding: '12px 16px',
					borderRadius: '10px',
					backgroundColor: 'rgba(64, 169, 255, 0.08)',
					border: '1px solid rgba(64, 169, 255, 0.22)',
					color: '#cce6ff',
					fontSize: '13px',
					lineHeight: '1.5',
					marginBottom: '24px',
				}}
			>
				<Info size={18} style={{ color: '#40a9ff', flexShrink: 0, marginTop: '2px' }} />
				<div style={{ flex: 1 }}>
					<strong>Direct In-Memory Session:</strong> The document you supply resides exclusively in browser memory. No text is stored in database tables, vector indexes, or server disks. Your document and Q&amp;A history will be lost upon refreshing or closing the browser.
				</div>
			</div>

			{/* Error Banner */}
			{error && (
				<div
					role="alert"
					style={{
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						gap: '12px',
						padding: '12px 16px',
						borderRadius: '10px',
						backgroundColor: 'rgba(245, 34, 45, 0.12)',
						border: '1px solid rgba(245, 34, 45, 0.3)',
						color: '#ff7875',
						fontSize: '13px',
						marginBottom: '24px',
					}}
				>
					<div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
						<AlertCircle size={18} />
						<span>{error.message || 'An error occurred during Self Search.'}</span>
					</div>
					<button
						type="button"
						onClick={clearError}
						style={{
							background: 'transparent',
							border: 'none',
							color: '#ff7875',
							cursor: 'pointer',
							fontSize: '12px',
							textDecoration: 'underline',
						}}
					>
						Dismiss
					</button>
				</div>
			)}

			{/* Main Grid: Document Area and Search Section */}
			<div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '24px' }}>
				{/* 1. Document Input Panel */}
				<div
					className="panel"
					style={{
						padding: '20px 24px',
						display: 'flex',
						flexDirection: 'column',
						gap: '14px',
					}}
				>
					<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
						<div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
							<FileText size={18} style={{ color: 'var(--soft)' }} />
							<span style={{ fontWeight: 600, fontSize: '14px', color: '#f1f1f1', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
								Source Document
							</span>
						</div>
						<div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
							<span
								style={{
									fontSize: '12px',
									color: docLength > MAX_DOC_LENGTH ? '#ff7875' : 'var(--muted)',
									fontFamily: 'monospace',
								}}
								aria-label="Character count"
							>
								{docLength.toLocaleString()} / {MAX_DOC_LENGTH.toLocaleString()} chars
							</span>
							{document && (
								<button
									type="button"
									onClick={clearDocument}
									style={{
										display: 'inline-flex',
										alignItems: 'center',
										gap: '6px',
										background: 'rgba(255, 255, 255, 0.05)',
										border: '1px solid rgba(255, 255, 255, 0.1)',
										color: 'var(--soft)',
										padding: '4px 10px',
										borderRadius: '6px',
										fontSize: '12px',
										cursor: 'pointer',
									}}
									title="Clear document text"
									aria-label="Clear document"
								>
									<RotateCcw size={12} />
									Clear document
								</button>
							)}
						</div>
					</div>

					<textarea
						aria-label="Document text"
						id="self-search-document-input"
						placeholder="Paste or type your document here (up to 100,000 characters)...&#10;&#10;Example:&#10;&quot;Cats bark loudly at night. Dogs can fly in the sky. Birds live in trees.&quot;"
						value={document}
						onChange={(e) => setDocument(e.target.value)}
						maxLength={MAX_DOC_LENGTH}
						rows={8}
						style={{
							width: '100%',
							background: 'rgba(15, 15, 15, 0.7)',
							border: '1px solid rgba(255, 255, 255, 0.12)',
							borderRadius: '8px',
							padding: '14px 16px',
							color: '#f5f5f5',
							fontSize: '14px',
							lineHeight: '1.6',
							resize: 'vertical',
							minHeight: '160px',
							outline: 'none',
							fontFamily: 'inherit',
						}}
					/>
				</div>

				{/* 2. Question Input Panel */}
				<div
					className="panel"
					style={{
						padding: '20px 24px',
						display: 'flex',
						flexDirection: 'column',
						gap: '14px',
					}}
				>
					<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
						<div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
							<HelpCircle size={18} style={{ color: 'var(--soft)' }} />
							<span style={{ fontWeight: 600, fontSize: '14px', color: '#f1f1f1', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
								Natural-Language Question
							</span>
						</div>
						<span
							style={{
								fontSize: '12px',
								color: qLength > MAX_QUESTION_LENGTH ? '#ff7875' : 'var(--muted)',
								fontFamily: 'monospace',
							}}
						>
							{qLength.toLocaleString()} / {MAX_QUESTION_LENGTH.toLocaleString()} chars
						</span>
					</div>

					<form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px', alignItems: 'stretch' }}>
						<input
							type="text"
							aria-label="Ask a question"
							id="self-search-question-input"
							placeholder={
								isDocEmpty
									? 'Please paste a document above first...'
									: 'Ask anything based on the document above (e.g. "How do cats sound?")...'
							}
							value={question}
							onChange={(e) => setQuestion(e.target.value)}
							onKeyDown={handleKeyDown}
							maxLength={MAX_QUESTION_LENGTH}
							disabled={loading}
							style={{
								flex: 1,
								background: 'rgba(15, 15, 15, 0.7)',
								border: '1px solid rgba(255, 255, 255, 0.12)',
								borderRadius: '8px',
								padding: '12px 16px',
								color: '#f5f5f5',
								fontSize: '14px',
								outline: 'none',
							}}
						/>
						<button
							type="submit"
							id="self-search-submit-button"
							disabled={loading || isDocEmpty || isQEmpty}
							style={{
								display: 'inline-flex',
								alignItems: 'center',
								gap: '8px',
								padding: '12px 22px',
								borderRadius: '8px',
								backgroundColor: loading || isDocEmpty || isQEmpty ? 'rgba(255, 255, 255, 0.08)' : '#f1f1f1',
								color: loading || isDocEmpty || isQEmpty ? 'var(--muted)' : '#111',
								border: 'none',
								fontWeight: 600,
								fontSize: '14px',
								cursor: loading || isDocEmpty || isQEmpty ? 'not-allowed' : 'pointer',
								transition: 'all 0.15s ease',
							}}
						>
							{loading ? (
								<>
									<span
										style={{
											width: '14px',
											height: '14px',
											border: '2px solid rgba(0,0,0,0.2)',
											borderTopColor: '#111',
											borderRadius: '50%',
											display: 'inline-block',
											animation: 'spin 0.8s linear infinite',
										}}
									/>
									Searching...
								</>
							) : (
								<>
									<Search size={16} />
									Search
								</>
							)}
						</button>
					</form>
				</div>

				{/* Navigation Tabs (Current Answer vs Session History) */}
				<div style={{ display: 'flex', gap: '12px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '8px' }}>
					<button
						type="button"
						onClick={() => setActiveTab('current')}
						style={{
							background: 'transparent',
							border: 'none',
							borderBottom: activeTab === 'current' ? '2px solid #f1f1f1' : '2px solid transparent',
							color: activeTab === 'current' ? '#f1f1f1' : 'var(--muted)',
							padding: '8px 12px',
							fontSize: '14px',
							fontWeight: 600,
							cursor: 'pointer',
						}}
					>
						Latest Answer
					</button>
					<button
						type="button"
						onClick={() => setActiveTab('history')}
						style={{
							background: 'transparent',
							border: 'none',
							borderBottom: activeTab === 'history' ? '2px solid #f1f1f1' : '2px solid transparent',
							color: activeTab === 'history' ? '#f1f1f1' : 'var(--muted)',
							padding: '8px 12px',
							fontSize: '14px',
							fontWeight: 600,
							cursor: 'pointer',
							display: 'inline-flex',
							alignItems: 'center',
							gap: '6px',
						}}
					>
						Q&amp;A History
						{history.length > 0 && (
							<span
								style={{
									fontSize: '11px',
									background: 'rgba(255,255,255,0.1)',
									padding: '2px 6px',
									borderRadius: '10px',
								}}
							>
								{history.length}
							</span>
						)}
					</button>
				</div>

				{/* 3. Latest Answer Section */}
				{activeTab === 'current' && (
					<>
						{!answer && !loading && (
							<div
								style={{
									padding: '40px 20px',
									textAlign: 'center',
									color: 'var(--muted)',
									border: '1px dashed rgba(255, 255, 255, 0.1)',
									borderRadius: '12px',
								}}
							>
								<FileSearch size={32} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
								<p style={{ fontSize: '14px', color: 'var(--soft)' }}>No query submitted yet.</p>
								<p style={{ fontSize: '13px', marginTop: '6px' }}>
									Paste text into the source document above and submit a question to view grounded answers and verified citations.
								</p>
							</div>
						)}

						{loading && (
							<div
								style={{
									padding: '48px 20px',
									textAlign: 'center',
									color: 'var(--soft)',
									background: 'rgba(255,255,255,0.02)',
									borderRadius: '12px',
									border: '1px solid rgba(255,255,255,0.06)',
								}}
							>
								<div
									style={{
										width: '28px',
										height: '28px',
										border: '3px solid rgba(255,255,255,0.15)',
										borderTopColor: '#f1f1f1',
										borderRadius: '50%',
										margin: '0 auto 16px',
										animation: 'spin 0.8s linear infinite',
									}}
								/>
								<p style={{ fontWeight: 600, fontSize: '15px' }}>Searching document &amp; verifying citations...</p>
								<p style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '4px' }}>
									Cross-checking extracted passages against source text
								</p>
							</div>
						)}

						{answer && !loading && (
							<AnswerCard answer={answer} />
						)}
					</>
				)}

				{/* 4. Session Q&A History Section */}
				{activeTab === 'history' && (
					<div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
						<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
							<span style={{ fontSize: '13px', color: 'var(--muted)' }}>
								{history.length} {history.length === 1 ? 'question' : 'questions'} answered this session
							</span>
							{history.length > 0 && (
								<button
									type="button"
									onClick={clearHistory}
									style={{
										display: 'inline-flex',
										alignItems: 'center',
										gap: '6px',
										background: 'transparent',
										border: 'none',
										color: 'var(--muted)',
										fontSize: '12px',
										cursor: 'pointer',
									}}
								>
									<Trash2 size={13} />
									Clear history
								</button>
							)}
						</div>

						{history.length === 0 ? (
							<div
								style={{
									padding: '40px 20px',
									textAlign: 'center',
									color: 'var(--muted)',
									border: '1px dashed rgba(255, 255, 255, 0.1)',
									borderRadius: '12px',
								}}
							>
								<p>No search history yet in this browser session.</p>
							</div>
						) : (
							history.map((item) => (
								<div
									key={item.id}
									className="panel"
									style={{
										padding: '16px 20px',
										display: 'flex',
										flexDirection: 'column',
										gap: '12px',
									}}
								>
									<div
										style={{
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'center',
											cursor: 'pointer',
										}}
										onClick={() => toggleHistoryItem(item.id)}
									>
										<div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
											{item.response.is_supported ? (
												<CheckCircle2 size={16} style={{ color: '#52c41a' }} />
											) : (
												<AlertTriangle size={16} style={{ color: '#faad14' }} />
											)}
											<strong style={{ fontSize: '14px', color: '#f1f1f1' }}>{item.question}</strong>
										</div>
										<div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
											<span style={{ fontSize: '11px', color: 'var(--muted)' }}>
												{new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
											</span>
											{expandedHistoryId === item.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
										</div>
									</div>

									{expandedHistoryId === item.id && (
										<div style={{ marginTop: '8px', paddingTop: '12px', borderTop: '1px solid rgba(255, 255, 255, 0.08)' }}>
											<AnswerCard answer={item.response} />
										</div>
									)}
								</div>
							))
						)}
					</div>
				)}
			</div>
		</div>
	)
}

/**
 * Reusable Answer and Passages Card.
 */
function AnswerCard({ answer }) {
	const isUnsupported = !answer.is_supported || answer.confidence === 'unsupported'

	return (
		<div
			className="panel"
			style={{
				padding: '24px',
				display: 'flex',
				flexDirection: 'column',
				gap: '20px',
				border: isUnsupported ? '1px solid rgba(250, 173, 20, 0.3)' : '1px solid rgba(255, 255, 255, 0.12)',
			}}
		>
			{/* Unsupported Warning Banner */}
			{isUnsupported && (
				<div
					role="alert"
					style={{
						display: 'flex',
						alignItems: 'flex-start',
						gap: '12px',
						padding: '14px 18px',
						borderRadius: '8px',
						backgroundColor: 'rgba(250, 173, 20, 0.1)',
						border: '1px solid rgba(250, 173, 20, 0.3)',
						color: '#ffe58f',
						fontSize: '13px',
						lineHeight: '1.5',
					}}
				>
					<ShieldAlert size={20} style={{ color: '#faad14', flexShrink: 0, marginTop: '2px' }} />
					<div>
						<strong style={{ display: 'block', fontSize: '14px', marginBottom: '2px', color: '#fff1b8' }}>
							Information Not Available in Document
						</strong>
						The provided document does not contain sufficient verified evidence to answer this question. The model has avoided inventing facts.
					</div>
				</div>
			)}

			{/* Answer Content */}
			<div>
				<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
					<span
						style={{
							fontSize: '12px',
							fontWeight: 700,
							letterSpacing: '0.05em',
							textTransform: 'uppercase',
							color: 'var(--soft)',
						}}
					>
						Synthesized Answer
					</span>
					<div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
						<span
							style={{
								fontSize: '11px',
								fontWeight: 600,
								textTransform: 'uppercase',
								padding: '2px 8px',
								borderRadius: '12px',
								backgroundColor:
									answer.confidence === 'high'
										? 'rgba(82, 196, 26, 0.15)'
										: answer.confidence === 'medium'
											? 'rgba(24, 144, 255, 0.15)'
											: 'rgba(250, 173, 20, 0.15)',
								color:
									answer.confidence === 'high'
										? '#73d13d'
										: answer.confidence === 'medium'
											? '#69c0ff'
											: '#ffc53d',
								border: `1px solid ${
									answer.confidence === 'high'
										? 'rgba(82, 196, 26, 0.3)'
										: answer.confidence === 'medium'
											? 'rgba(24, 144, 255, 0.3)'
											: 'rgba(250, 173, 20, 0.3)'
								}`,
							}}
						>
							Confidence: {answer.confidence}
						</span>
					</div>
				</div>

				<div
					style={{
						fontSize: '15px',
						lineHeight: '1.65',
						color: '#f9f9f9',
						background: 'rgba(255, 255, 255, 0.02)',
						padding: '16px 18px',
						borderRadius: '8px',
						borderLeft: isUnsupported ? '3px solid #faad14' : '3px solid #52c41a',
					}}
				>
					{answer.answer}
				</div>

				{answer.explanation && (
					<p style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '10px', fontStyle: 'italic' }}>
						Note: {answer.explanation}
					</p>
				)}
			</div>

			{/* Supporting Passages Section */}
			<div>
				<div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
					<span
						style={{
							fontSize: '12px',
							fontWeight: 700,
							letterSpacing: '0.05em',
							textTransform: 'uppercase',
							color: 'var(--soft)',
						}}
					>
						Supporting Passages &amp; Citations ({answer.source_passages?.length || 0})
					</span>
				</div>

				{(!answer.source_passages || answer.source_passages.length === 0) ? (
					<p style={{ fontSize: '13px', color: 'var(--muted)', fontStyle: 'italic' }}>
						No citations available.
					</p>
				) : (
					<div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
						{answer.source_passages.map((passage, idx) => (
							<div
								key={idx}
								style={{
									padding: '14px 16px',
									borderRadius: '8px',
									background: 'rgba(0, 0, 0, 0.25)',
									border: passage.verified ? '1px solid rgba(82, 196, 26, 0.3)' : '1px solid rgba(250, 173, 20, 0.3)',
									display: 'flex',
									flexDirection: 'column',
									gap: '8px',
								}}
							>
								<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '6px' }}>
									<div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
										{passage.verified ? (
											<span
												style={{
													display: 'inline-flex',
													alignItems: 'center',
													gap: '4px',
													fontSize: '11px',
													fontWeight: 600,
													color: '#52c41a',
													background: 'rgba(82, 196, 26, 0.1)',
													padding: '2px 8px',
													borderRadius: '4px',
												}}
											>
												<CheckCircle2 size={12} />
												VERIFIED CITATION
											</span>
										) : (
											<span
												style={{
													display: 'inline-flex',
													alignItems: 'center',
													gap: '4px',
													fontSize: '11px',
													fontWeight: 600,
													color: '#faad14',
													background: 'rgba(250, 173, 20, 0.1)',
													padding: '2px 8px',
													borderRadius: '4px',
												}}
											>
												<AlertTriangle size={12} />
												UNVERIFIED / ALTERED
											</span>
										)}
										<span style={{ fontSize: '11px', color: 'var(--muted)', textTransform: 'capitalize' }}>
											Relevance: {passage.relevance || 'direct'}
										</span>
									</div>

									{passage.start_offset != null && passage.end_offset != null && (
										<span style={{ fontSize: '11px', color: 'var(--muted)', fontFamily: 'monospace' }}>
											Offset: [{passage.start_offset}:{passage.end_offset}]
										</span>
									)}
								</div>

								<blockquote
									style={{
										margin: 0,
										fontSize: '13px',
										color: '#e4e4e4',
										fontStyle: 'italic',
										borderLeft: '2px solid rgba(255, 255, 255, 0.2)',
										paddingLeft: '12px',
									}}
								>
									&ldquo;{passage.text}&rdquo;
								</blockquote>
							</div>
						))}
					</div>
				)}
			</div>
		</div>
	)
}
