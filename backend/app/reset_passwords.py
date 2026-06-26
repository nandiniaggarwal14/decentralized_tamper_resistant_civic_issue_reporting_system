"""
One-time utility: Reset every user's password to '123456789'.
Run with: python -m backend.app.reset_passwords
"""
from backend.app.database import get_connection
from backend.app.auth import get_password_hash

NEW_PASSWORD = "123456789"

def main() -> None:
    new_hash = get_password_hash(NEW_PASSWORD)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, username FROM users")
            users = cursor.fetchall()
            print(f"Found {len(users)} user(s). Resetting passwords...")
            for u in users:
                cursor.execute(
                    "UPDATE users SET password = %s WHERE id = %s",
                    (new_hash, u["id"])
                )
                print(f"  [OK] Reset password for: {u['username']}")
        conn.commit()
    print("\nAll passwords have been reset to: 123456789")

    # Also approve any pending users so no one is locked out
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET is_approved = TRUE WHERE is_approved = FALSE RETURNING username")
            approved = cursor.fetchall()
            if approved:
                for u in approved:
                    print(f"  [OK] Auto-approved pending user: {u['username']}")
            else:
                print("  No pending users to approve.")
        conn.commit()
    print("\nDone! All users can now log in with their username and password: 123456789")

if __name__ == "__main__":
    main()
