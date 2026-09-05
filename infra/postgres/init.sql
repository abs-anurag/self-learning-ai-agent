CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    api_key_hash VARCHAR(64) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tasks
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    goal TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, running, succeeded, failed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Task Runs (authoritative execution state)
CREATE TABLE task_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, running, succeeded, failed
    termination_reason VARCHAR(50),
    iteration_count INT NOT NULL DEFAULT 0,
    sequence_counter INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Episodic Experiences (audit & provenance)
CREATE TABLE experiences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_type VARCHAR(50) NOT NULL,
    tools_used JSONB NOT NULL DEFAULT '[]',
    outcome_summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Composite Evaluations (ONE ROW PER COMPLETED ITERATION)
CREATE TABLE evaluations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    iteration_count INT NOT NULL, -- 1, 2, or 3
    task_success BOOLEAN NOT NULL,
    deterministic_pass BOOLEAN NOT NULL,
    tool_success BOOLEAN NOT NULL,
    judge_score NUMERIC(3, 1) NOT NULL,
    tool_call_count INT NOT NULL,
    payload JSONB NOT NULL, -- contains private judge_reasoning
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_run_iteration UNIQUE (run_id, iteration_count)
);

-- User Feedback
CREATE TABLE feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Recipe Candidates (pre-gate)
CREATE TABLE recipe_candidates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_type VARCHAR(50) NOT NULL,
    problem_pattern TEXT NOT NULL,
    context TEXT NOT NULL,
    recommended_strategy TEXT NOT NULL,
    successful_steps JSONB NOT NULL,
    failed_steps JSONB NOT NULL,
    tools_used JSONB NOT NULL,
    lesson TEXT NOT NULL,
    evidence TEXT NOT NULL,
    evaluation_score NUMERIC(3, 1) NOT NULL,
    deterministic_pass BOOLEAN NOT NULL,
    generalizable BOOLEAN NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'candidate', -- candidate, rejected
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Trusted Recipes (vector indexed)
CREATE TABLE task_recipes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'trusted',
    task_type VARCHAR(50) NOT NULL,
    problem_pattern TEXT NOT NULL,
    context TEXT NOT NULL,
    recommended_strategy TEXT NOT NULL,
    successful_steps JSONB NOT NULL,
    failed_steps JSONB NOT NULL,
    tools_used JSONB NOT NULL,
    lesson TEXT NOT NULL,
    evidence TEXT NOT NULL,
    evaluation_score NUMERIC(3, 1) NOT NULL,
    deterministic_pass BOOLEAN NOT NULL,
    generalizable BOOLEAN NOT NULL,
    confidence NUMERIC(3, 2) NOT NULL DEFAULT 1.0,
    version INT NOT NULL DEFAULT 1,
    usage_count INT NOT NULL DEFAULT 0,
    success_after_reuse INT NOT NULL DEFAULT 0,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Durable Telemetry Events
CREATE TABLE agent_events (
    event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sequence INT NOT NULL,
    schema_version VARCHAR(10) NOT NULL DEFAULT '1.0',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT uq_run_sequence UNIQUE (run_id, sequence)
);

-- Audit Logs
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    resource VARCHAR(100) NOT NULL,
    redacted_detail TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Key Performance Indexes
CREATE INDEX idx_tasks_user ON tasks(user_id, created_at DESC);
CREATE INDEX idx_task_runs_lookup ON task_runs(task_id, created_at DESC);
CREATE INDEX idx_task_runs_status ON task_runs(status);
CREATE INDEX idx_evaluations_run ON evaluations(run_id, iteration_count);
CREATE INDEX idx_agent_events_replay ON agent_events(run_id, sequence ASC);
CREATE INDEX idx_task_recipes_user ON task_recipes(user_id, task_type);
CREATE INDEX idx_task_recipes_embedding ON task_recipes USING hnsw (embedding vector_cosine_ops);