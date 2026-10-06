/**
 * Production-conforming mock event stream and data fixtures.
 * Strictly adheres to BLUEPRINT.md §14, §15, §21, §24 and backend/events/schema.py.
 *
 * 10 Durable Event Fields per envelope:
 *   event_id, task_id, run_id, user_id, sequence, schema_version,
 *   timestamp, event_type, status, metadata
 *
 * 11 Production Event Types (BLUEPRINT §14):
 *   task_started, planning_started, memory_retrieved, tool_started,
 *   tool_completed, evaluation_completed, reflection_completed,
 *   learning_candidate_created, learning_saved, task_completed, task_failed
 *
 * Node Order per BLUEPRINT §6 & §8:
 *   understand → retrieve_memory → plan → execute → observe → evaluate
 *   (On failure: reflect → replan → execute → observe → evaluate)
 *
 * Golden Demo (§24):
 *   Run A — 2 iterations, 2 tool calls (no prior recipe)
 *   Run B — 1 iteration, 1 tool call (recipe retrieved, 50% reduction)
 */

// ─── Allowlisted Event Types ───────────────────────────────────────────────
export const EVENT_TYPES = [
	'task_started',
	'planning_started',
	'memory_retrieved',
	'tool_started',
	'tool_completed',
	'evaluation_completed',
	'reflection_completed',
	'learning_candidate_created',
	'learning_saved',
	'task_completed',
	'task_failed',
]

// ─── Demo Identifiers ──────────────────────────────────────────────────────
const RUN_A_TASK_ID = 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d'
const RUN_A_RUN_ID  = 'e5f6g7h8-1234-5678-9abc-def012345678'
const RUN_B_TASK_ID = 'b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e'
const RUN_B_RUN_ID  = 'f6a7b8c9-0d1e-2f3a-4b5c-6d7e8f9a0b1c'
const DEMO_USER_ID  = '99999999-8888-7777-6666-555555555555'

// ─── Run A — Baseline (No Prior Recipe) ────────────────────────────────────
// BLUEPRINT §24: Run A — 2 iterations, 2 tool calls, creates trusted recipe
// Node order: understand → memory_retrieved(hits=0) → plan(iter1) →
//   execute(wrong formula) → evaluate(FAIL,iter1) → reflect →
//   replan(iter2) → execute(correct formula) → evaluate(SUCCESS,iter2) →
//   maybe_learn → learning_candidate_created → learning_saved → task_completed
export const mockEvents = [
	// ── Seq 1: Task accepted, graph initialized ──────────────────────────
	{
		event_id:       '11111111-0001-4000-8000-000000000001',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       1,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:00.120Z',
		event_type:     'task_started',
		status:         'running',
		metadata: {
			goal:      'Calculate the compound interest on $10,000 at 5% annual rate for 3 years, compounded monthly.',
			task_type: 'math',
		},
	},

	// ── Seq 2: retrieve_memory — BEFORE planning (BLUEPRINT §6) ─────────
	{
		event_id:       '11111111-0002-4000-8000-000000000002',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       2,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:01.050Z',
		event_type:     'memory_retrieved',
		status:         'running',
		metadata: {
			hits:      0,
			task_type: 'math',
			message:   'No trusted recipe found for current task pattern in memory bank.',
		},
	},

	// ── Seq 3: plan — Iteration 1 (baseline, without compounding frequency) ─
	{
		event_id:       '11111111-0003-4000-8000-000000000003',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       3,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:02.100Z',
		event_type:     'planning_started',
		status:         'running',
		metadata: {
			iteration: 1,
			plan: [
				'Normalize principal, rate, and term',
				'Apply simple compound formula: P * (1 + r) ** t',
				'Evaluate result against expected answer',
			],
		},
	},

	// ── Seq 4: execute — Tool call 1 (wrong formula, ignores monthly compounding) ─
	{
		event_id:       '11111111-0004-4000-8000-000000000004',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       4,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:03.200Z',
		event_type:     'tool_started',
		status:         'running',
		metadata: {
			tool_name:  'calculator',
			tool_input: { expression: '10000 * (1 + 0.05) ** 3' },
		},
	},

	// ── Seq 5: observe — Tool 1 result ──────────────────────────────────
	{
		event_id:       '11111111-0005-4000-8000-000000000005',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       5,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:04.080Z',
		event_type:     'tool_completed',
		status:         'running',
		metadata: {
			tool_name:   'calculator',
			status:      'succeeded',
			duration_ms: 184,
			result:      11576.25,
		},
	},

	// ── Seq 6: evaluate — Iteration 1 FAILURE (wrong result, iter_count=1) ─
	{
		event_id:       '11111111-0006-4000-8000-000000000006',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       6,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:05.420Z',
		event_type:     'evaluation_completed',
		status:         'running',
		metadata: {
			iteration_count:    1,
			task_success:       false,
			deterministic_pass: false,
			tool_success:       true,
			judge_score:        5.5,
			tool_call_count:    1,
		},
	},

	// ── Seq 7: reflect — Diagnosis: formula needs monthly compounding ────
	{
		event_id:       '11111111-0007-4000-8000-000000000007',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       7,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:06.650Z',
		event_type:     'reflection_completed',
		status:         'running',
		metadata: {
			iteration_count:  1,
			diagnosis:        'Compounding frequency n=12 was neglected. Correct formula: A = P * (1 + r/n)**(n*t).',
			replan_strategy:  'Apply with n=12: 10000 * (1 + 0.05/12)**(12*3)',
		},
	},

	// ── Seq 8: replan — Iteration 2 with corrected formula ──────────────
	{
		event_id:       '11111111-0008-4000-8000-000000000008',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       8,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:07.200Z',
		event_type:     'planning_started',
		status:         'running',
		metadata: {
			iteration: 2,
			plan: [
				'Apply full compound frequency formula: A = P * (1 + r/n)**(n*t)',
				'Use n=12 (monthly), P=10000, r=0.05, t=3',
				'Verify output matches expected value ~$11,614.72',
			],
		},
	},

	// ── Seq 9: execute — Tool call 2 (correct formula) ──────────────────
	{
		event_id:       '11111111-0009-4000-8000-000000000009',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       9,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:08.100Z',
		event_type:     'tool_started',
		status:         'running',
		metadata: {
			tool_name:  'calculator',
			tool_input: { expression: '10000 * (1 + 0.05/12) ** (12*3)' },
		},
	},

	// ── Seq 10: observe — Tool 2 result (correct) ───────────────────────
	{
		event_id:       '11111111-0010-4000-8000-000000000010',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       10,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:09.300Z',
		event_type:     'tool_completed',
		status:         'running',
		metadata: {
			tool_name:   'calculator',
			status:      'succeeded',
			duration_ms: 201,
			result:      11614.72,
		},
	},

	// ── Seq 11: evaluate — Iteration 2 SUCCESS (iter_count=2) ───────────
	{
		event_id:       '11111111-0011-4000-8000-000000000011',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       11,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:10.500Z',
		event_type:     'evaluation_completed',
		status:         'running',
		metadata: {
			iteration_count:    2,
			task_success:       true,
			deterministic_pass: true,
			tool_success:       true,
			judge_score:        9.0,
			tool_call_count:    2,
		},
	},

	// ── Seq 12: maybe_learn — candidate extracted ────────────────────────
	{
		event_id:       '11111111-0012-4000-8000-000000000012',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       12,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:11.200Z',
		event_type:     'learning_candidate_created',
		status:         'running',
		metadata: {
			task_type:            'math',
			problem_pattern:      'compound interest with compounding frequency',
			recommended_strategy: 'Apply formula A = P*(1 + r/n)**(n*t) directly via calculator',
			evaluation_score:     9.0,
			deterministic_pass:   true,
			generalizable:        true,
		},
	},

	// ── Seq 13: quality gate PASSED → promoted to pgvector ──────────────
	{
		event_id:       '11111111-0013-4000-8000-000000000013',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       13,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:12.100Z',
		event_type:     'learning_saved',
		status:         'running',
		metadata: {
			recipe_id:         'r1r2r3r4-5678-9abc-def0-123456789abc',
			task_type:         'math',
			learning_decision: 'promoted',
			judge_score:       9.0,
			vector_indexed:    true,
		},
	},

	// ── Seq 14: task_completed — terminal state: succeeded ───────────────
	{
		event_id:       '11111111-0014-4000-8000-000000000014',
		task_id:        RUN_A_TASK_ID,
		run_id:         RUN_A_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       14,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:00:13.500Z',
		event_type:     'task_completed',
		status:         'succeeded',
		metadata: {
			final_response:  'The compound interest is $1,614.72 (Total balance: $11,614.72).',
			iteration_count: 2,
			total_tool_calls: 2,
			task_success:    true,
		},
	},
]

// ─── Run B — Learned (Recipe Retrieved) ────────────────────────────────────
// BLUEPRINT §24: Run B — 1 iteration, 1 tool call, recipe retrieved
// 50% reduction in both iterations and tool calls vs Run A
export const mockRunBEvents = [
	// ── Seq 1: Task accepted ────────────────────────────────────────────
	{
		event_id:       '22222222-0001-4000-8000-000000000001',
		task_id:        RUN_B_TASK_ID,
		run_id:         RUN_B_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       1,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:30:00.120Z',
		event_type:     'task_started',
		status:         'running',
		metadata: {
			goal:      'Calculate the compound interest on $5,000 at 7% annual rate for 5 years, compounded quarterly.',
			task_type: 'math',
		},
	},

	// ── Seq 2: retrieve_memory — Recipe HIT (demo fixture returns Run A recipe) ─
	{
		event_id:       '22222222-0002-4000-8000-000000000002',
		task_id:        RUN_B_TASK_ID,
		run_id:         RUN_B_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       2,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:30:01.050Z',
		event_type:     'memory_retrieved',
		status:         'running',
		metadata: {
			hits:                 1,
			task_type:            'math',
			recipe_id:            'r1r2r3r4-5678-9abc-def0-123456789abc',
			problem_pattern:      'compound interest with compounding frequency',
			recommended_strategy: 'Apply formula A = P*(1 + r/n)**(n*t) directly via calculator',
			similarity_score:     0.94,
		},
	},

	// ── Seq 3: plan — Iteration 1 (cites retrieved recipe) ──────────────
	{
		event_id:       '22222222-0003-4000-8000-000000000003',
		task_id:        RUN_B_TASK_ID,
		run_id:         RUN_B_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       3,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:30:02.100Z',
		event_type:     'planning_started',
		status:         'running',
		metadata: {
			iteration: 1,
			plan: [
				'Retrieved recipe advises: A = P*(1 + r/n)**(n*t)',
				'Apply with n=4 (quarterly), P=5000, r=0.07, t=5',
				'Verify output against expected value ~$7,073.89',
			],
			recipe_cited: true,
		},
	},

	// ── Seq 4: execute — Tool call 1 (correct formula on first attempt) ──
	{
		event_id:       '22222222-0004-4000-8000-000000000004',
		task_id:        RUN_B_TASK_ID,
		run_id:         RUN_B_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       4,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:30:03.200Z',
		event_type:     'tool_started',
		status:         'running',
		metadata: {
			tool_name:  'calculator',
			tool_input: { expression: '5000 * (1 + 0.07/4) ** (4*5)' },
		},
	},

	// ── Seq 5: observe — Tool result (correct on first try) ─────────────
	{
		event_id:       '22222222-0005-4000-8000-000000000005',
		task_id:        RUN_B_TASK_ID,
		run_id:         RUN_B_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       5,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:30:04.080Z',
		event_type:     'tool_completed',
		status:         'running',
		metadata: {
			tool_name:   'calculator',
			status:      'succeeded',
			duration_ms: 178,
			result:      7073.89,
		},
	},

	// ── Seq 6: evaluate — Iteration 1 SUCCESS (iter_count=1) ─────────────
	{
		event_id:       '22222222-0006-4000-8000-000000000006',
		task_id:        RUN_B_TASK_ID,
		run_id:         RUN_B_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       6,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:30:05.420Z',
		event_type:     'evaluation_completed',
		status:         'running',
		metadata: {
			iteration_count:    1,
			task_success:       true,
			deterministic_pass: true,
			tool_success:       true,
			judge_score:        9.2,
			tool_call_count:    1,
		},
	},

	// ── Seq 7: task_completed — duplicate check suppresses new recipe ─────
	// BLUEPRINT §10: similarity >= 0.90 → learning_decision = 'skip'
	{
		event_id:       '22222222-0007-4000-8000-000000000007',
		task_id:        RUN_B_TASK_ID,
		run_id:         RUN_B_RUN_ID,
		user_id:        DEMO_USER_ID,
		sequence:       7,
		schema_version: '1.0',
		timestamp:      '2026-09-23T10:30:06.900Z',
		event_type:     'task_completed',
		status:         'succeeded',
		metadata: {
			final_response:   'The compound interest is $2,073.89 (Total balance: $7,073.89).',
			iteration_count:  1,
			total_tool_calls: 1,
			task_success:     true,
			learning_decision: 'skip',
		},
	},
]

// ─── Failure Demonstration Events ──────────────────────────────────────────
// Separate fixture — demonstrates max_iterations terminal failure handling
// NOT appended to Run A or Run B streams
export const mockFailedEvents = [
	{
		event_id:       '33333333-0001-4000-8000-000000000001',
		task_id:        'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a',
		run_id:         '1e2f3a4b-5c6d-7e8f-9a0b-1c2d3e4f5a6b',
		user_id:        DEMO_USER_ID,
		sequence:       1,
		schema_version: '1.0',
		timestamp:      '2026-09-22T19:45:22.000Z',
		event_type:     'task_failed',
		status:         'failed',
		metadata: {
			error_code:          'MAX_ITERATIONS',
			termination_reason:  'max_iterations',
			message:             'Task could not be solved within 3 iterations.',
		},
	},
]

// ─── Mock Task Records ──────────────────────────────────────────────────────
// Matches GET /tasks response schema: { items, page, page_size, total }
// BLUEPRINT §15 — field is `goal` not `prompt`; `task_id` not `id`
export const mockTasks = [
	{
		task_id:    RUN_A_TASK_ID,
		goal:       'Calculate compound interest on $10,000 at 5% annual rate for 3 years, compounded monthly.',
		status:     'succeeded',
		task_type:  'math',
		created_at: '2026-09-23T10:00:00Z',
		updated_at: '2026-09-23T10:00:14Z',
		runs: [
			{
				run_id:             RUN_A_RUN_ID,
				status:             'succeeded',
				termination_reason: 'success',
				iteration_count:    2,
				created_at:         '2026-09-23T10:00:00Z',
			},
		],
	},
	{
		task_id:    RUN_B_TASK_ID,
		goal:       'Calculate the compound interest on $5,000 at 7% annual rate for 5 years, compounded quarterly.',
		status:     'succeeded',
		task_type:  'math',
		created_at: '2026-09-23T10:30:00Z',
		updated_at: '2026-09-23T10:30:07Z',
		runs: [
			{
				run_id:             RUN_B_RUN_ID,
				status:             'succeeded',
				termination_reason: 'success',
				iteration_count:    1,
				created_at:         '2026-09-23T10:30:00Z',
			},
		],
	},
	{
		task_id:    'c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f',
		goal:       'Scan financial disclosure files and summarize quarterly risk factors.',
		status:     'running',
		task_type:  'file',
		created_at: '2026-09-23T07:30:00Z',
		updated_at: '2026-09-23T07:30:15Z',
		runs: [
			{
				run_id:             '0d1e2f3a-4b5c-6d7e-8f9a-0b1c2d3e4f5a',
				status:             'running',
				termination_reason: null,
				iteration_count:    1,
				created_at:         '2026-09-23T07:30:00Z',
			},
		],
	},
	{
		task_id:    'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a',
		goal:       'Verify multi-variable break-even threshold with unconstrained debt amortization.',
		status:     'failed',
		task_type:  'math',
		created_at: '2026-09-22T19:45:00Z',
		updated_at: '2026-09-22T19:45:22Z',
		runs: [
			{
				run_id:             '1e2f3a4b-5c6d-7e8f-9a0b-1c2d3e4f5a6b',
				status:             'failed',
				termination_reason: 'max_iterations',
				iteration_count:    3,
				created_at:         '2026-09-22T19:45:00Z',
			},
		],
	},
]

// ─── Mock Recipe Records ────────────────────────────────────────────────────
// Matches GET /memory/recipes response schema: { items, page, page_size, total }
// BLUEPRINT §15 — fields: recipe_id, task_type, problem_pattern,
//   recommended_strategy, usage_count, success_after_reuse, created_at
export const mockRecipes = [
	{
		recipe_id:            'r1r2r3r4-5678-9abc-def0-123456789abc',
		task_type:            'math',
		problem_pattern:      'compound interest with compounding frequency',
		recommended_strategy: 'Apply formula A = P*(1 + r/n)**(n*t) directly via calculator',
		usage_count:          14,
		success_after_reuse:  12,
		created_at:           '2026-09-23T10:00:12Z',
	},
	{
		recipe_id:            'r2r3r4r5-6789-abcd-ef01-23456789abcd',
		task_type:            'research',
		problem_pattern:      'multi-source vendor comparison under strict budget limits',
		recommended_strategy: 'Query Tavily with focused keyword tuples; cross-reference pricing tables before synthesis.',
		usage_count:          8,
		success_after_reuse:  7,
		created_at:           '2026-09-22T14:20:00Z',
	},
	{
		recipe_id:            'r3r4r5r6-789a-bcde-f012-3456789abcde',
		task_type:            'file',
		problem_pattern:      'multi-file risk aggregation and section extraction',
		recommended_strategy: 'Inspect directory manifest first; read target section buffers under 500KB cap.',
		usage_count:          5,
		success_after_reuse:  5,
		created_at:           '2026-09-21T18:05:00Z',
	},
]

// ─── Mock Metrics Record ────────────────────────────────────────────────────
// Matches GET /metrics 11-field response schema (BLUEPRINT §15)
export const mockMetrics = {
	total_tasks:            20,
	successful_tasks:       17,
	failed_tasks:           3,
	success_rate:           0.85,
	average_iterations:     1.7,
	average_tool_calls:     2.1,
	recipes_promoted:       4,
	recipe_retrieval_count: 9,
	successful_reuses:      8,
	average_judge_score:    8.2,
	improvement_rate:       0.44,
}

// ─── Integration Aliases & Failed Run Fixtures ──────────────────────────────
export const MOCK_EVENTS_RUN_A = mockEvents;
export const MOCK_EVENTS_RUN_B = mockRunBEvents;

const MOCK_TASK_ID_FAIL = 'aaaaaaaa-0000-4000-8000-000000000003';
const MOCK_RUN_ID_FAIL  = 'bbbbbbbb-0000-4000-8000-000000000003';

function isoNow(offsetSeconds = 0) {
	return new Date(Date.now() + offsetSeconds * 1000).toISOString();
}

function mockEnvelopeFail(sequence, event_type, status, metadata = {}) {
	return {
		event_id: `ffffffff-0000-4000-${String(sequence).padStart(4, '0')}-000000000003`,
		task_id: MOCK_TASK_ID_FAIL,
		run_id: MOCK_RUN_ID_FAIL,
		user_id: DEMO_USER_ID,
		sequence,
		schema_version: '1.0',
		timestamp: isoNow(sequence + 200),
		event_type,
		status,
		metadata,
	};
}

export const MOCK_EVENTS_FAILED = [
	mockEnvelopeFail(1, 'task_started', 'running', {
		task_type: 'research',
		goal: 'Find the current population of Mars.',
	}),
	mockEnvelopeFail(2, 'memory_retrieved', 'running', { hits: 0, task_type: 'research' }),
	mockEnvelopeFail(3, 'planning_started', 'running', { iteration: 1 }),
	mockEnvelopeFail(4, 'tool_started', 'running', { tool_name: 'web_search', iteration: 1 }),
	mockEnvelopeFail(5, 'tool_completed', 'running', {
		tool_name: 'web_search',
		iteration: 1,
		status: 'succeeded',
		result_summary: 'No reliable source found for Mars population.',
	}),
	mockEnvelopeFail(6, 'evaluation_completed', 'running', {
		iteration_count: 1,
		task_success: false,
		deterministic_pass: false,
		tool_success: true,
		judge_score: 2.0,
		tool_call_count: 1,
	}),
	mockEnvelopeFail(7, 'reflection_completed', 'running', {
		iteration: 1,
		diagnosis_summary: 'Mars is not inhabited; task is unanswerable.',
	}),
	mockEnvelopeFail(8, 'planning_started', 'running', { iteration: 2 }),
	mockEnvelopeFail(9, 'evaluation_completed', 'running', {
		iteration_count: 2,
		task_success: false,
		judge_score: 2.0,
		tool_call_count: 1,
	}),
	mockEnvelopeFail(10, 'reflection_completed', 'running', { iteration: 2, diagnosis_summary: 'Still unanswerable.' }),
	mockEnvelopeFail(11, 'planning_started', 'running', { iteration: 3 }),
	mockEnvelopeFail(12, 'evaluation_completed', 'failed', {
		iteration_count: 3,
		task_success: false,
		judge_score: 2.0,
		tool_call_count: 1,
	}),
	mockEnvelopeFail(13, 'task_failed', 'failed', {
		termination_reason: 'max_iterations',
		message: 'Task could not be solved within 3 iterations.',
	}),
];

// ─── Playback Utilities ─────────────────────────────────────────────────────
let _playbackTimerId = null;

export function playMockEvents({
	events = MOCK_EVENTS_RUN_A,
	intervalMs = 800,
	onEvent,
	onComplete,
	onConnectionStatus,
} = {}) {
	stopMockEvents();

	if (typeof onConnectionStatus === 'function') {
		onConnectionStatus('connecting');
		setTimeout(() => onConnectionStatus('connected'), 100);
	}

	const sorted = [...events].sort((a, b) => a.sequence - b.sequence);
	let index = 0;

	function deliverNext() {
		if (index >= sorted.length) {
			_playbackTimerId = null;
			if (typeof onConnectionStatus === 'function') onConnectionStatus('disconnected');
			if (typeof onComplete === 'function') onComplete();
			return;
		}
		if (typeof onEvent === 'function') {
			try {
				onEvent(sorted[index]);
			} catch {
				// Prevent callback errors from breaking playback
			}
		}
		index++;
		_playbackTimerId = setTimeout(deliverNext, intervalMs);
	}

	_playbackTimerId = setTimeout(deliverNext, 150);
}

export function stopMockEvents() {
	if (_playbackTimerId !== null) {
		clearTimeout(_playbackTimerId);
		_playbackTimerId = null;
	}
}

export function isMockPlaybackActive() {
	return _playbackTimerId !== null;
}

export const MOCK_TASK_IDS = {
	runA: RUN_A_TASK_ID,
	runB: RUN_B_TASK_ID,
	failed: MOCK_TASK_ID_FAIL,
};

export const MOCK_RUN_IDS = {
	runA: RUN_A_RUN_ID,
	runB: RUN_B_RUN_ID,
	failed: MOCK_RUN_ID_FAIL,
};

export default {
	mockEvents,
	mockRunBEvents,
	mockTasks,
	mockRecipes,
	mockMetrics,
	MOCK_EVENTS_RUN_A,
	MOCK_EVENTS_RUN_B,
	MOCK_EVENTS_FAILED,
	playMockEvents,
	stopMockEvents,
	isMockPlaybackActive,
	MOCK_TASK_IDS,
	MOCK_RUN_IDS,
};
