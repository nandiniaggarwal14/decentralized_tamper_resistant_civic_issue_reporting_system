import math
from typing import Optional
from backend.app.database import get_connection

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return R * c

def find_nearest_ward(latitude: float, longitude: float) -> Optional[int]:
    """Find the ward whose center is closest to the given coordinates."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, center_latitude, center_longitude, radius_meters FROM wards")
            wards = cursor.fetchall()
            
    if not wards:
        return None

    nearest_ward_id = None
    min_distance = float('inf')

    for ward in wards:
        dist = haversine_distance(latitude, longitude, ward["center_latitude"], ward["center_longitude"])
        # If it's within the ward's radius or it's simply the closest ward overall
        if dist < min_distance:
            min_distance = dist
            nearest_ward_id = ward["id"]

    return nearest_ward_id

def classify_issue(category: str) -> Optional[int]:
    """Return the department ID mapped to the given category."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT department_id FROM category_department_map WHERE category = %s",
                (category,)
            )
            row = cursor.fetchone()
            if row:
                return row["department_id"]
            
            # Fallback: find default or first department
            cursor.execute("SELECT id FROM departments LIMIT 1")
            row = cursor.fetchone()
            if row:
                return row["id"]
                
    return None
