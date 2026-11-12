import shutil
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smriti.config import load_settings

def reset_user_data() -> None:
    settings = load_settings()
    db_path = settings.db_path
    upload_dir = settings.upload_dir

    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")

    # Check preserved patient logins
    patients = cur.execute("SELECT id, alias, username FROM patient").fetchall()
    print(f"Preserving {len(patients)} patient login(s):")
    for pid, alias, username in patients:
        print(f"  - Username: {username or '(none)'} | Alias: {alias} | ID: {pid}")

    # Remove user-generated medical documents and associated data
    cur.execute("DELETE FROM document")
    cur.execute("DELETE FROM medication")
    cur.execute("DELETE FROM stage_artifact")
    cur.execute("DELETE FROM share_token")

    # Clean audit logs except account/auth actions
    cur.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    cur.execute("DELETE FROM audit WHERE entity NOT IN ('patient', 'auth')")
    cur.execute(
        """
        CREATE TRIGGER audit_no_delete
        BEFORE DELETE ON audit
        BEGIN
            SELECT RAISE(ABORT, 'audit is append-only');
        END;
        """
    )

    conn.commit()
    cur.execute("VACUUM")
    conn.close()

    # Clean up uploaded page images
    deleted_files = 0
    if upload_dir.exists():
        for item in upload_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
                deleted_files += 1
            elif item.is_file() and item.name != ".gitkeep":
                item.unlink()
                deleted_files += 1

    print(f"Cleared all document records, observations, reports, jobs, and {deleted_files} upload directory items.")
    print("User credentials and login details remain intact.")

if __name__ == "__main__":
    reset_user_data()
