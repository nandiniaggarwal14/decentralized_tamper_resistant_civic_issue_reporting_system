-- Tamper simulation for Neon PostgreSQL
-- Purpose: modify existing issue data directly in DB to test tamper detection.
--
-- IMPORTANT:
-- 1) Run only in test/dev.
-- 2) This intentionally changes issue data without updating on-chain hash.
-- 3) Verify from UI/API after running this script.

BEGIN;

-- Option A (default): tamper the most recently created issue.
UPDATE issues
SET
    description = description || ' [tampered-in-db]',
    area = area || ' - altered'
WHERE id = (
    SELECT id
    FROM issues
    ORDER BY created_at DESC
    LIMIT 1
);

-- Option B: tamper one specific issue by UUID (uncomment and set your id).
-- UPDATE issues
-- SET title = title || ' [tampered]'
-- WHERE id = 'PUT-ISSUE-UUID-HERE';

COMMIT;

-- Basic latitude update by issue id (run separately as needed):
-- UPDATE issues
-- SET latitude = 12.9716
-- WHERE id = 'PUT-ISSUE-UUID-HERE';
