"""Seed script — populates wards, departments, and category-department mappings.

Run once after schema migration:
    python -m backend.app.seed

Safe to re-run: uses INSERT ... ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

from backend.app.database import get_connection, init_db


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------
DEPARTMENTS = [
    ("Roads & Infrastructure", "Potholes, broken roads, footpath damage, traffic signals"),
    ("Water Supply", "Water leakage, contamination, pipeline damage, water shortage"),
    ("Electricity", "Street lights, power outage, exposed wiring, transformer issues"),
    ("Sanitation & Waste", "Garbage collection, open drains, sewage overflow, public toilets"),
    ("Public Safety", "Accidents, unsafe structures, stray animals, fire hazards"),
    ("Parks & Environment", "Tree falls, park maintenance, pollution, illegal dumping"),
    ("General Administration", "Encroachment, noise complaints, licensing issues, miscellaneous"),
]

# ---------------------------------------------------------------------------
# Category → Department mapping (rule-based classification)
# ---------------------------------------------------------------------------
CATEGORY_DEPARTMENT_MAP = {
    # Roads & Infrastructure
    "Road": "Roads & Infrastructure",
    "Pothole": "Roads & Infrastructure",
    "Footpath": "Roads & Infrastructure",
    "Traffic": "Roads & Infrastructure",
    "Bridge": "Roads & Infrastructure",
    "Infrastructure": "Roads & Infrastructure",
    # Water Supply
    "Water": "Water Supply",
    "Pipeline": "Water Supply",
    "Drainage": "Water Supply",
    "Flooding": "Water Supply",
    # Electricity
    "Electricity": "Electricity",
    "Street Light": "Electricity",
    "Power": "Electricity",
    "Wiring": "Electricity",
    # Sanitation & Waste
    "Garbage": "Sanitation & Waste",
    "Sanitation": "Sanitation & Waste",
    "Sewage": "Sanitation & Waste",
    "Waste": "Sanitation & Waste",
    "Toilet": "Sanitation & Waste",
    # Public Safety
    "Safety": "Public Safety",
    "Accident": "Public Safety",
    "Fire": "Public Safety",
    "Stray Animal": "Public Safety",
    # Parks & Environment
    "Park": "Parks & Environment",
    "Tree": "Parks & Environment",
    "Pollution": "Parks & Environment",
    "Environment": "Parks & Environment",
    # General
    "Encroachment": "General Administration",
    "Noise": "General Administration",
    "Other": "General Administration",
}

# ---------------------------------------------------------------------------
# Sample wards (Indian cities — center coordinates + radius in meters)
# ---------------------------------------------------------------------------
WARDS = [
    ("Ward 1 - Connaught Place", 28.6315, 77.2167, 3000),
    ("Ward 2 - Chandni Chowk", 28.6506, 77.2309, 2500),
    ("Ward 3 - Karol Bagh", 28.6519, 77.1905, 2500),
    ("Ward 4 - Saket", 28.5244, 77.2066, 3000),
    ("Ward 5 - Dwarka", 28.5921, 77.0460, 4000),
    ("Ward 6 - Rohini", 28.7495, 77.0565, 3500),
    ("Ward 7 - Laxmi Nagar", 28.6304, 77.2773, 2500),
    ("Ward 8 - Janakpuri", 28.6219, 77.0815, 3000),
]


def seed_departments(cursor) -> dict[str, int]:
    """Insert departments and return a name → id mapping."""
    dept_ids: dict[str, int] = {}
    for name, description in DEPARTMENTS:
        cursor.execute(
            """
            INSERT INTO departments (name, description)
            VALUES (%s, %s)
            ON CONFLICT (name) DO NOTHING
            RETURNING id
            """,
            (name, description),
        )
        row = cursor.fetchone()
        if row:
            dept_ids[name] = row["id"]

    # Fetch any existing departments that were skipped by ON CONFLICT
    cursor.execute("SELECT id, name FROM departments")
    for row in cursor.fetchall():
        dept_ids[row["name"]] = row["id"]

    return dept_ids


def seed_category_map(cursor, dept_ids: dict[str, int]) -> None:
    """Insert category → department mappings."""
    for category, dept_name in CATEGORY_DEPARTMENT_MAP.items():
        dept_id = dept_ids.get(dept_name)
        if dept_id is None:
            print(f"  Warning: department '{dept_name}' not found, skipping category '{category}'")
            continue
        cursor.execute(
            """
            INSERT INTO category_department_map (category, department_id)
            VALUES (%s, %s)
            ON CONFLICT (category) DO NOTHING
            """,
            (category, dept_id),
        )


def seed_wards(cursor) -> None:
    """Insert sample wards (no ward member assigned yet)."""
    for name, lat, lng, radius in WARDS:
        cursor.execute(
            """
            INSERT INTO wards (name, center_latitude, center_longitude, radius_meters)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO NOTHING
            """,
            (name, lat, lng, radius),
        )


def seed_users(cursor) -> None:
    """Seed the administrator and citizen accounts."""
    import uuid
    from backend.app.auth import get_password_hash
    
    # 1. Seed admin
    admin_id = str(uuid.uuid4())
    admin_password = get_password_hash("123456789")
    cursor.execute(
        """
        INSERT INTO users (id, username, password, role, full_name, contact, is_approved)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (admin_id, "admin", admin_password, "admin", "System Administrator", "admin@civicportal.gov", True)
    )
    print("  Seeded admin user: admin / 123456789")

    # 2. No other users are seeded by default to keep the database fresh and only contain the admin



def main() -> None:
    # Ensure schema is up to date
    init_db()

    with get_connection() as conn:
        with conn.cursor() as cursor:
            print("Cleaning up database (truncating tables)...")
            cursor.execute(
                """
                TRUNCATE users, wards, departments, category_department_map, 
                         issues, issue_votes, issue_status_history, failed_blockchain_txns 
                CASCADE
                """
            )

            print("Seeding departments...")
            dept_ids = seed_departments(cursor)
            print(f"  {len(dept_ids)} departments ready")

            print("Seeding category-department mappings...")
            seed_category_map(cursor, dept_ids)
            print(f"  {len(CATEGORY_DEPARTMENT_MAP)} category mappings processed")

            print("Seeding wards...")
            seed_wards(cursor)
            print(f"  {len(WARDS)} wards processed")

            print("Seeding admin and citizen users...")
            seed_users(cursor)

        conn.commit()

    print("\nSeed complete.")



if __name__ == "__main__":
    main()
