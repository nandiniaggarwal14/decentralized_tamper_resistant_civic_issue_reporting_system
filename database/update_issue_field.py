import os
import uuid
from pathlib import Path

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

ALLOWED_COLUMNS = {
    "title": "text",
    "description": "text",
    "category": "text",
    "area": "text",
    "address": "text",
    "latitude": "float",
    "longitude": "float",
    "reporter_name": "text",
    "contact": "text",
    "image_url": "text",
    "hash": "text",
    "status": "status",
    "upvote_count": "int",
    "downvote_count": "int",
}

ALLOWED_STATUS = {"pending", "in_progress", "resolved", "rejected"}


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Add it to .env")
    return database_url


def parse_value(column: str, raw_value: str):
    value_type = ALLOWED_COLUMNS[column]

    if value_type == "float":
        return float(raw_value)
    if value_type == "int":
        return int(raw_value)
    if value_type == "status":
        status_value = raw_value.strip().lower()
        if status_value not in ALLOWED_STATUS:
            allowed = ", ".join(sorted(ALLOWED_STATUS))
            raise ValueError(f"Invalid status. Allowed values: {allowed}")
        return status_value

    return raw_value


def main() -> None:
    print("Update a single column in issues table")

    issue_id_input = input("Issue UUID: ").strip()
    try:
        issue_id = str(uuid.UUID(issue_id_input))
    except ValueError as exc:
        raise ValueError("Invalid UUID format.") from exc

    print("Allowed columns:", ", ".join(sorted(ALLOWED_COLUMNS.keys())))
    column = input("Column to change: ").strip()
    if column not in ALLOWED_COLUMNS:
        raise ValueError("Column is not allowed.")

    raw_value = input("New value: ").strip()
    value = parse_value(column, raw_value)

    confirm = input(
        f"Confirm update issues.{column} for id={issue_id}? (yes/no): "
    ).strip().lower()
    if confirm not in {"y", "yes"}:
        print("Cancelled.")
        return

    with psycopg2.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            update_query = sql.SQL("UPDATE issues SET {} = %s WHERE id = %s").format(
                sql.Identifier(column)
            )
            cursor.execute(update_query, (value, issue_id))
            conn.commit()

            if cursor.rowcount == 0:
                print("No row updated. Check if issue id exists.")
                return

            select_query = sql.SQL("SELECT {} FROM issues WHERE id = %s").format(
                sql.Identifier(column)
            )
            cursor.execute(select_query, (issue_id,))
            updated_value = cursor.fetchone()[0]

    print(f"Updated successfully. {column}={updated_value}")


if __name__ == "__main__":
    main()
