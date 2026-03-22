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
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'resolved', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS issue_votes (
    issue_id UUID NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    voter_id VARCHAR(255) NOT NULL,
    vote_type VARCHAR(10) NOT NULL CHECK (vote_type IN ('up', 'down')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (issue_id, voter_id)
);

ALTER TABLE issues
    ADD COLUMN IF NOT EXISTS upvote_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS downvote_count INTEGER NOT NULL DEFAULT 0;

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

CREATE INDEX IF NOT EXISTS idx_issues_created_at ON issues(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);
CREATE INDEX IF NOT EXISTS idx_issues_area ON issues(area);
CREATE INDEX IF NOT EXISTS idx_issues_category ON issues(category);
CREATE INDEX IF NOT EXISTS idx_issue_votes_issue_id ON issue_votes(issue_id);
CREATE INDEX IF NOT EXISTS idx_issue_votes_voter_id ON issue_votes(voter_id);
