import pytest
from unittest.mock import MagicMock
from backend.app.routing import haversine_distance, find_nearest_ward, classify_issue

def test_haversine_distance_calculation():
    # CP coordinate
    lat1, lon1 = 28.6304, 77.2177
    # Karol Bagh coordinate
    lat2, lon2 = 28.6449, 77.1878
    
    dist = haversine_distance(lat1, lon1, lat2, lon2)
    # distance should be roughly 3.3km (3300 meters)
    assert 3000 < dist < 4000

def test_find_nearest_ward(mock_db):
    # Mocking wards table rows
    mock_db.fetchall.return_value = [
        {"id": 1, "name": "Ward A", "center_latitude": 28.6304, "center_longitude": 77.2177, "radius_meters": 3000},
        {"id": 2, "name": "Ward B", "center_latitude": 28.5244, "center_longitude": 77.2066, "radius_meters": 3000}
    ]
    
    # query coordinates close to Ward A
    nearest_id = find_nearest_ward(28.6310, 77.2180)
    assert nearest_id == 1

def test_classify_issue_success(mock_db):
    # Mocking category department map query returns dept_id = 4
    mock_db.fetchone.return_value = {"department_id": 4}
    
    dept_id = classify_issue("Pothole")
    assert dept_id == 4

def test_classify_issue_fallback(mock_db):
    # Mock map query returns None (not found), then fallback returns default dept_id = 1
    mock_db.fetchone.side_effect = [None, {"id": 1}]
    
    dept_id = classify_issue("Unknown Issue Category")
    assert dept_id == 1
