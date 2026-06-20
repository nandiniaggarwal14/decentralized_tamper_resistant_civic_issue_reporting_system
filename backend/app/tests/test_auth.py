import pytest
from unittest.mock import MagicMock, patch
from backend.app.auth import get_password_hash, verify_password

def test_password_hashing():
    pw = "my-secure-password"
    pw_hash = get_password_hash(pw)
    assert verify_password(pw, pw_hash) is True
    assert verify_password("wrong-pass", pw_hash) is False

def test_register_citizen_success(client, mock_db):
    # Username check returns None (not taken)
    mock_db.fetchone.return_value = None

    payload = {
        "username": "citizen_test",
        "password": "password123",
        "role": "citizen",
        "full_name": "Citizen Test",
        "contact": "1234567890"
    }
    
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_register_ward_member_success(client, mock_db):
    # Username check returns None (not taken)
    mock_db.fetchone.return_value = None

    payload = {
        "username": "ward_test",
        "password": "password123",
        "role": "ward_member",
        "full_name": "Ward Test",
        "contact": "1234567890",
        "ward_id": 1
    }
    
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_register_duplicate_username(client, mock_db):
    # Username check returns a row (taken)
    mock_db.fetchone.return_value = {"id": "some-existing-id"}

    payload = {
        "username": "citizen_test",
        "password": "password123",
        "role": "citizen",
        "full_name": "Citizen Test",
        "contact": "1234567890"
    }
    
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 400
    assert "already taken" in response.json()["detail"]

def test_login_success(client, mock_db):
    # Mock user row for auth fetch user
    pw_hash = get_password_hash("password123")
    mock_db.fetchone.return_value = {
        "id": "11111111-2222-3333-4444-555555555555",
        "username": "user1",
        "password_hash": pw_hash,
        "role": "citizen",
        "full_name": "User One",
        "contact": "123",
        "is_approved": True,
        "department_id": None,
        "department_name": None
    }
    
    payload = {
        "username": "user1",
        "password": "password123"
    }
    response = client.post("/api/auth/json-login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "citizen"
    assert "access_token" in data

def test_login_incorrect_password(client, mock_db):
    # Mock user row
    pw_hash = get_password_hash("password123")
    mock_db.fetchone.return_value = {
        "id": "11111111-2222-3333-4444-555555555555",
        "username": "user1",
        "password_hash": pw_hash,
        "role": "citizen",
        "full_name": "User One",
        "contact": "123",
        "is_approved": True,
        "department_id": None,
        "department_name": None
    }
    
    payload = {
        "username": "user1",
        "password": "wrong-password"
    }
    response = client.post("/api/auth/json-login", json=payload)
    assert response.status_code == 401
    assert "Incorrect username or password" in response.json()["detail"]

def test_role_checker_guard(client, mock_db):
    # Create token for citizen
    from backend.app.auth import create_access_token
    token = create_access_token({"sub": "some-id", "role": "citizen"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Mock /api/auth/me profile fetch
    mock_db.fetchone.return_value = {
        "id": "11111111-2222-3333-4444-555555555555",
        "username": "citizen1",
        "role": "citizen",
        "full_name": "Citizen User",
        "contact": "123",
        "is_approved": True,
        "department_id": None,
        "department_name": None
    }
    
    # Access ward endpoint with citizen token -> expect 403 Forbidden
    response = client.get("/api/ward/issues", headers=headers)
    assert response.status_code == 403
