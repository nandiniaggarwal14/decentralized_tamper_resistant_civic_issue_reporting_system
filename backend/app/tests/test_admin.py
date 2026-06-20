import pytest
from unittest.mock import MagicMock, patch

def test_admin_pending_users_requires_admin(client):
    # Citizen trying to access pending users -> expect 403
    from backend.app.auth import create_access_token
    token = create_access_token({"sub": "citizen-id", "role": "citizen"})
    headers = {"Authorization": f"Bearer {token}"}
    
    response = client.get("/api/admin/pending-users", headers=headers)
    assert response.status_code == 403

def test_admin_get_pending_users_success(client, mock_db, auth_headers):
    # Mock admin profile fetch
    mock_db.fetchone.side_effect = [
        # profile fetch for admin
        {
            "id": "admin-uuid",
            "username": "admin",
            "role": "admin",
            "full_name": "Admin User",
            "contact": "admin@",
            "is_approved": True,
            "department_id": None,
            "department_name": None
        }
    ]
    # Mock fetching user list from db
    mock_db.fetchall.return_value = [
        {"id": "user-uuid-1", "username": "ward1", "role": "ward_member", "full_name": "Ward Official", "contact": "111", "is_approved": False, "ward_id": 1, "department_id": None, "created_at": None}
    ]
    
    response = client.get("/api/admin/pending-users", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert len(response.json()["data"]) == 1

def test_admin_approve_user_success(client, mock_db, auth_headers):
    # Mock admin profile fetch
    mock_db.fetchone.side_effect = [
        # profile fetch for admin
        {
            "id": "admin-uuid",
            "username": "admin",
            "role": "admin",
            "full_name": "Admin User",
            "contact": "admin@",
            "is_approved": True,
            "department_id": None,
            "department_name": None
        },
        # target user exists check
        {"id": "user-uuid-1"}
    ]
    
    response = client.post("/api/admin/approve-user/user-uuid-1", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_admin_reject_user_success(client, mock_db, auth_headers):
    # Mock admin profile fetch
    mock_db.fetchone.side_effect = [
        # profile fetch for admin
        {
            "id": "admin-uuid",
            "username": "admin",
            "role": "admin",
            "full_name": "Admin User",
            "contact": "admin@",
            "is_approved": True,
            "department_id": None,
            "department_name": None
        },
        # target user exists check
        {"id": "user-uuid-1"}
    ]
    
    response = client.post("/api/admin/reject-user/user-uuid-1", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_admin_get_failed_transactions(client, mock_db, auth_headers):
    mock_db.fetchone.side_effect = [
        # profile fetch for admin
        {
            "id": "admin-uuid",
            "username": "admin",
            "role": "admin",
            "full_name": "Admin User",
            "contact": "admin@",
            "is_approved": True,
            "department_id": None,
            "department_name": None
        }
    ]
    # Mock queue query
    from datetime import datetime, timezone
    mock_db.fetchall.return_value = [
        {
            "id": 1,
            "function_name": "store_issue_hash",
            "args_json": "{}",
            "error_message": "Infura timeout",
            "retry_count": 0,
            "created_at": datetime.now(timezone.utc),
            "resolved_at": None
        }
    ]
    
    response = client.get("/api/admin/failed-transactions", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert len(response.json()["data"]) == 1

def test_admin_retry_blockchain_queue(client, mock_db, auth_headers):
    mock_db.fetchone.side_effect = [
        # profile fetch for admin
        {
            "id": "admin-uuid",
            "username": "admin",
            "role": "admin",
            "full_name": "Admin User",
            "contact": "admin@",
            "is_approved": True,
            "department_id": None,
            "department_name": None
        }
    ]
    
    with patch("backend.app.blockchain_service.retry_failed_transactions", return_value=(2, 0)):
        response = client.post("/api/admin/retry-blockchain", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "Successes: 2" in response.json()["message"]
