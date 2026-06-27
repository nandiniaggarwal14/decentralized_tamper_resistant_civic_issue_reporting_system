-- ===========================================================================
-- Decentralized Tamper-Resistant Civic Issue Reporting System
-- Database Schema (Neon PostgreSQL)
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. Core tables (created first — no foreign-key dependencies)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('citizen', 'ward_member', 'authority', 'admin')),
    full_name VARCHAR(255) NOT NULL,
    contact VARCHAR(100),
    is_approved BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT
);

-- ---------------------------------------------------------------------------
-- 2. Tables that reference core tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS wards (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    center_latitude DOUBLE PRECISION NOT NULL,
    center_longitude DOUBLE PRECISION NOT NULL,
    radius_meters DOUBLE PRECISION NOT NULL DEFAULT 5000,
    ward_member_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ipfs_cid TEXT,
    blockchain_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS government_personnel (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    designation VARCHAR(255),
    ipfs_cid TEXT,
    blockchain_hash TEXT
);

CREATE TABLE IF NOT EXISTS category_department_map (
    category VARCHAR(100) PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id)
);

-- ---------------------------------------------------------------------------
-- 3. Issues table (original — unchanged columns kept as-is)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS issues (
    id UUID PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(100) NOT NULL,
    area VARCHAR(255) NOT NULL,
    address TEXT,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    reporter_name VARCHAR(255) NOT NULL,
    contact VARCHAR(255),
    image_url TEXT,
    hash TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'resolved', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 4. Issue votes table (original)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS issue_votes (
    issue_id UUID NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    voter_id VARCHAR(255) NOT NULL,
    vote_type VARCHAR(10) NOT NULL CHECK (vote_type IN ('up', 'down')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (issue_id, voter_id)
);

-- ---------------------------------------------------------------------------
-- 5. Expand issues table with new columns (safe — IF NOT EXISTS)
-- ---------------------------------------------------------------------------

-- Original expansion columns (vote counts + hash)
ALTER TABLE issues
    ADD COLUMN IF NOT EXISTS upvote_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS downvote_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS hash TEXT;

-- New expansion columns (Phase 1 — routing, IPFS, multi-media, completion)
ALTER TABLE issues
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS ward_id INTEGER REFERENCES wards(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    ADD COLUMN IF NOT EXISTS ipfs_cid TEXT,
    ADD COLUMN IF NOT EXISTS media_urls JSONB DEFAULT '[]'::JSONB,
    ADD COLUMN IF NOT EXISTS completion_proof_ipfs_cid TEXT,
    ADD COLUMN IF NOT EXISTS completion_hash TEXT;

-- ---------------------------------------------------------------------------
-- 6. Status change audit trail
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS issue_status_history (
    id UUID PRIMARY KEY,
    issue_id UUID NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    old_status VARCHAR(50),
    new_status VARCHAR(50) NOT NULL,
    changed_by UUID NOT NULL REFERENCES users(id),
    comments TEXT,
    proof_url TEXT,
    ipfs_cid TEXT,
    blockchain_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 7. Recompute denormalized vote counts (idempotent)
-- ---------------------------------------------------------------------------

UPDATE issues AS i
SET
    upvote_count = COALESCE(v.upvotes, 0),
    downvote_count = COALESCE(v.downvotes, 0)
FROM (
    SELECT
        issue_id,
        SUM(CASE WHEN vote_type = 'up' THEN 1 ELSE 0 END)::INTEGER AS upvotes,
        SUM(CASE WHEN vote_type = 'down' THEN 1 ELSE 0 END)::INTEGER AS downvotes
    FROM issue_votes
    GROUP BY issue_id
) AS v
WHERE i.id = v.issue_id;

UPDATE issues AS i
SET
    upvote_count = 0,
    downvote_count = 0
WHERE NOT EXISTS (
    SELECT 1
    FROM issue_votes iv
    WHERE iv.issue_id = i.id
);

-- ---------------------------------------------------------------------------
-- 8. Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_issues_created_at ON issues(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);
CREATE INDEX IF NOT EXISTS idx_issues_area ON issues(area);
CREATE INDEX IF NOT EXISTS idx_issues_category ON issues(category);
CREATE INDEX IF NOT EXISTS idx_issues_ward_id ON issues(ward_id);
CREATE INDEX IF NOT EXISTS idx_issues_department_id ON issues(department_id);
CREATE INDEX IF NOT EXISTS idx_issues_user_id ON issues(user_id);
CREATE INDEX IF NOT EXISTS idx_issues_priority ON issues(priority);
CREATE INDEX IF NOT EXISTS idx_issue_votes_issue_id ON issue_votes(issue_id);
CREATE INDEX IF NOT EXISTS idx_issue_votes_voter_id ON issue_votes(voter_id);
CREATE INDEX IF NOT EXISTS idx_wards_ward_member_id ON wards(ward_member_id);
CREATE INDEX IF NOT EXISTS idx_govt_personnel_dept ON government_personnel(department_id);
CREATE INDEX IF NOT EXISTS idx_status_history_issue ON issue_status_history(issue_id);
CREATE INDEX IF NOT EXISTS idx_status_history_changed_by ON issue_status_history(changed_by);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- ---------------------------------------------------------------------------
-- 9. Blockchain Retry Queue
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS failed_blockchain_txns (
    id SERIAL PRIMARY KEY,
    function_name VARCHAR(100) NOT NULL,
    args_json TEXT NOT NULL,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- 10. Database Schema Migrations (for compatibility with existing databases)
-- ---------------------------------------------------------------------------

-- Add is_approved column to users if not exists
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT TRUE;

-- Drop and recreate role constraint to include 'admin'
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('citizen', 'ward_member', 'authority', 'admin'));

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_users_is_approved ON users(is_approved);

-- Add ipfs_cid column to issue_status_history if not exists
ALTER TABLE issue_status_history ADD COLUMN IF NOT EXISTS ipfs_cid TEXT;

-- Add blockchain_hash column to issue_status_history if not exists
ALTER TABLE issue_status_history ADD COLUMN IF NOT EXISTS blockchain_hash TEXT;
