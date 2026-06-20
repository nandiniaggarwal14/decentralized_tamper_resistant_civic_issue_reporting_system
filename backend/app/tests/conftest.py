import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Define the mock connection and cursor globally for tests
mock_cursor = MagicMock()
mock_conn = MagicMock()
mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
mock_conn.__enter__.return_value = mock_conn

# Mock get_connection at the database module level immediately
import backend.app.database
backend.app.database.get_connection = MagicMock(return_value=mock_conn)

# Also mock it where it might have been imported already
import backend.app.auth
backend.app.auth.get_connection = backend.app.database.get_connection

import backend.app.main
backend.app.main.get_connection = backend.app.database.get_connection

import backend.app.routing
backend.app.routing.get_connection = backend.app.database.get_connection

import backend.app.blockchain_service
backend.app.blockchain_service.get_connection = backend.app.database.get_connection

last_execute_query = ""
last_execute_vars = None

def mock_execute(query, vars=None):
    global last_execute_query, last_execute_vars
    last_execute_query = query
    last_execute_vars = vars

def mock_fetchone_fallback():
    global last_execute_query, last_execute_vars
    
    # Check if a custom return_value was set by the test
    ret = mock_cursor.fetchone.return_value
    if ret != "default_sentinel":
        return ret
        
    if not last_execute_query:
        return None
    q = last_execute_query.lower()
    
    # If checking user profile
    if "select u.id" in q and "from users" in q:
        user_id = last_execute_vars[0] if last_execute_vars else None
        role = "citizen"
        if user_id == "admin" or (user_id and "admin" in str(user_id)):
            role = "admin"
        elif user_id and "ward" in str(user_id):
            role = "ward_member"
        elif user_id and ("auth" in str(user_id) or "dept" in str(user_id) or "offic" in str(user_id)):
            role = "authority"
            
        return {
            "id": user_id or "default-user-uuid",
            "username": str(user_id) if user_id else "mocked_user",
            "role": role,
            "full_name": "Mocked User",
            "contact": "mock@test.com",
            "is_approved": True,
            "department_id": 1 if role == "authority" else None,
            "department_name": "Sanitation" if role == "authority" else None,
            "ward_id": 1 if role == "ward_member" else None,
            "ward_name": "Connaught Place" if role == "ward_member" else None
        }
    return None

@pytest.fixture(autouse=True)
def mock_db():
    global last_execute_query, last_execute_vars
    last_execute_query = ""
    last_execute_vars = None
    
    mock_cursor.reset_mock()
    mock_conn.reset_mock()
    
    # Reset mock behaviors to dynamic defaults
    mock_cursor.execute.side_effect = mock_execute
    mock_cursor.fetchone.side_effect = mock_fetchone_fallback
    mock_cursor.fetchone.return_value = "default_sentinel"
    mock_cursor.fetchall.side_effect = None
    mock_cursor.fetchall.return_value = []
    
    yield mock_cursor


@pytest.fixture(autouse=True)
def mock_blockchain():
    with patch("backend.app.blockchain_service.is_blockchain_active", return_value=True), \
         patch("backend.app.blockchain_service.store_issue_hash", return_value="mock_txn_hash"), \
         patch("backend.app.blockchain_service.get_issue_hash", return_value="mock_data_hash"), \
         patch("backend.app.blockchain_service.store_personnel_hash", return_value="mock_personnel_hash"), \
         patch("backend.app.blockchain_service.get_personnel_hash", return_value="mock_personnel_hash"), \
         patch("backend.app.blockchain_service.store_completion_hash", return_value="mock_completion_hash"), \
         patch("backend.app.blockchain_service.get_completion_hash", return_value="mock_completion_hash"):
        yield

@pytest.fixture(autouse=True)
def mock_ipfs():
    with patch("backend.app.ipfs_service.store_json", return_value="QmTestCidJson1234567890"), \
         patch("backend.app.ipfs_service.store_file", return_value="QmTestCidFile1234567890"), \
         patch("backend.app.ipfs_service.get_ipfs_data", return_value={"test": "data"}):
        yield

@pytest.fixture
def client():
    from backend.app.main import app
    with TestClient(app) as c:
        yield c

@pytest.fixture
def auth_headers():
    from backend.app.auth import create_access_token
    token = create_access_token({"sub": "admin", "role": "admin"})
    return {"Authorization": f"Bearer {token}"}

