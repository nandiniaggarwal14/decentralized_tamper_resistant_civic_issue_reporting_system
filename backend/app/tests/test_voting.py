import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

def test_vote_requires_auth(client):
    response = client.post("/api/issues/11111111-2222-3333-4444-555555555555/vote", json={"vote_type": "up"})
    assert response.status_code == 401

def test_vote_cooldown_rate_limit(client, mock_db):
    from backend.app.auth import create_access_token
    token = create_access_token({"sub": "citizen-id", "role": "citizen"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Mock user profile fetch and cooldown check using side_effect
    mock_db.fetchone.side_effect = [
        # profile fetch
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "username": "citizen1",
            "role": "citizen",
            "full_name": "Citizen User",
            "contact": "123",
            "is_approved": True,
            "department_id": None,
            "department_name": None
        },
        # check cooldown (returns a vote cast 2 seconds ago)
        {"created_at": datetime.now(timezone.utc)}
    ]
    
    response = client.post(
        "/api/issues/11111111-2222-3333-4444-555555555555/vote",
        json={"vote_type": "up"},
        headers=headers
    )
    assert response.status_code == 429
    assert "Voting too fast" in response.json()["detail"]

def test_vote_toggle_upvote_to_remove(client, mock_db):
    from backend.app.auth import create_access_token
    token = create_access_token({"sub": "citizen-id", "role": "citizen"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Mock profile fetch and vote logic queries
    mock_db.fetchone.side_effect = [
        # 1. profile fetch
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "username": "citizen1",
            "role": "citizen",
            "full_name": "Citizen User",
            "contact": "123",
            "is_approved": True,
            "department_id": None,
            "department_name": None
        },
        # 2. check cooldown (None -> no recent vote)
        None,
        # 3. check issue existence
        {"id": "11111111-2222-3333-4444-555555555555"},
        # 4. returning vote result after removal
        {"user_vote": None},
        # 5. returning vote counts
        {"upvotes": 0, "downvotes": 0}
    ]
    
    response = client.post(
        "/api/issues/11111111-2222-3333-4444-555555555555/vote",
        json={"vote_type": "up"},
        headers=headers
    )
    assert response.status_code == 200
    assert response.json()["data"]["user_vote"] is None
