import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

def test_validate_coordinates_failure(client):
    from backend.app.auth import create_access_token
    token = create_access_token({"sub": "citizen-id", "role": "citizen"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Coordinates out of range: Latitude = 95.0
    payload = {
        "title": "Broken pipe",
        "description": "Contamination in pipelines",
        "category": "Water Supply",
        "area": "Connaught Place",
        "address": "Block B CP",
        "latitude": 95.0,
        "longitude": 77.2,
        "reporter_name": "John Doe",
        "contact": "9999"
    }
    
    response = client.post("/api/issues", data=payload, headers=headers)
    assert response.status_code == 400
    assert "Latitude must be between -90 and 90" in response.json()["detail"]

def test_file_validation_magic_bytes_failure(client):
    from backend.app.auth import create_access_token
    token = create_access_token({"sub": "citizen-id", "role": "citizen"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Submit a file with fake content (does not match image magic bytes or pdf)
    fake_file = ("test.jpg", b"fake file content that has no magic bytes")
    
    payload = {
        "title": "Broken pipe",
        "description": "Contamination in pipelines",
        "category": "Water Supply",
        "area": "Connaught Place",
        "address": "Block B CP",
        "latitude": 28.6,
        "longitude": 77.2,
        "reporter_name": "John Doe",
        "contact": "9999"
    }
    
    response = client.post(
        "/api/issues",
        data=payload,
        files={"image": fake_file},
        headers=headers
    )
    assert response.status_code == 400
    assert "magic bytes verification failed" in response.json()["detail"]

def test_rate_limiting_submission_failure(client, mock_db):
    from backend.app.auth import create_access_token
    token = create_access_token({"sub": "citizen-id", "role": "citizen"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Mock database to return user profile first, then a recent submission timestamp (e.g. 5 seconds ago)
    # This triggers the rate limiting cooldown of 30 seconds
    mock_db.fetchone.side_effect = [
        {
            "id": "citizen-id",
            "username": "citizen_test",
            "role": "citizen",
            "full_name": "Citizen User",
            "contact": "123",
            "is_approved": True,
            "department_id": None,
            "department_name": None
        },
        {"created_at": datetime.now(timezone.utc)}
    ]
    
    payload = {
        "title": "Pothole",
        "description": "Big pothole on road",
        "category": "Roads & Infrastructure",
        "area": "Dwarka",
        "latitude": 28.6,
        "longitude": 77.0,
        "reporter_name": "Reporter A"
    }
    
    response = client.post("/api/issues", data=payload, headers=headers)
    assert response.status_code == 429
    assert "Too many requests" in response.json()["detail"]

def test_get_public_issues(client, mock_db):
    # Mock fetching multiple issues from db
    mock_db.fetchall.return_value = [
        {
            "id": "11111111-2222-3333-4444-555555555555",
            "title": "Road Pothole",
            "description": "Damaged asphalt",
            "category": "Roads & Infrastructure",
            "area": "Saket",
            "address": "Main Road",
            "latitude": 28.5,
            "longitude": 77.2,
            "reporter_name": "Citizen A",
            "contact": "123",
            "image_url": "http://img",
            "hash": "somehash",
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "priority": "medium",
            "ward_id": 1,
            "ward_name": "Ward 1",
            "department_id": 1,
            "department_name": "Infrastructure",
            "ipfs_cid": "Qm...",
            "media_urls": "[]",
            "completion_proof_ipfs_cid": None,
            "completion_hash": None,
            "upvote_count": 5,
            "downvote_count": 0,
            "user_vote": None
        }
    ]
    
    response = client.get("/api/issues")
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert len(response.json()["data"]) == 1
