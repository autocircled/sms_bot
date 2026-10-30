import sqlite3
import json
import os
from typing import Optional, List, Dict, Any

DEFAULT_DB_PATH = "data/jobs.db"


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Creates a connection to SQLite database and ensures parent directory exists."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH):
    """Initializes the jobs database schema."""
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                url TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                location TEXT,
                date_posted TEXT,
                job_schema TEXT,
                actual_apply_url TEXT,
                status TEXT DEFAULT 'pending_apply',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")
        conn.commit()


def save_guest_job(
    url: str,
    job_schema: Dict[str, Any],
    actual_apply_url: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH
) -> bool:
    """
    Saves or updates a job record obtained during guest scraping.
    Status is 'completed' if an apply URL is present, otherwise 'pending_apply'.
    """
    init_db(db_path)

    # Extract clean top-level fields for fast indexing & UI display
    title = job_schema.get("title", "N/A") if isinstance(job_schema, dict) else "N/A"
    
    hiring_org = job_schema.get("hiringOrganization") if isinstance(job_schema, dict) else None
    if isinstance(hiring_org, dict):
        company = hiring_org.get("name", "N/A")
    else:
        company = str(hiring_org or "N/A")

    job_loc = job_schema.get("jobLocation") if isinstance(job_schema, dict) else None
    if isinstance(job_loc, dict):
        address = job_loc.get("address")
        if isinstance(address, dict):
            location = address.get("addressLocality", "N/A")
        else:
            location = str(address or "N/A")
    else:
        location = str(job_loc or "N/A")

    date_posted = job_schema.get("datePosted", "") if isinstance(job_schema, dict) else ""
    schema_json_str = json.dumps(job_schema, ensure_ascii=False)
    status = "completed" if actual_apply_url else "pending_apply"

    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO jobs (url, title, company, location, date_posted, job_schema, actual_apply_url, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                date_posted = excluded.date_posted,
                job_schema = excluded.job_schema,
                actual_apply_url = COALESCE(excluded.actual_apply_url, jobs.actual_apply_url),
                status = CASE 
                    WHEN excluded.actual_apply_url IS NOT NULL THEN 'completed'
                    WHEN jobs.actual_apply_url IS NOT NULL THEN 'completed'
                    ELSE 'pending_apply'
                END,
                updated_at = CURRENT_TIMESTAMP;
        """, (url, title, company, location, date_posted, schema_json_str, actual_apply_url, status))
        conn.commit()
    return True


def update_job_apply_url(
    url: str,
    actual_apply_url: Optional[str],
    db_path: str = DEFAULT_DB_PATH
) -> bool:
    """
    Updates the apply URL for an existing job (Stage 2 Logged-in enrichment).
    Sets status to 'completed' if an apply URL is found.
    """
    init_db(db_path)
    status = "completed" if actual_apply_url else "pending_apply"

    with get_connection(db_path) as conn:
        cursor = conn.execute("""
            UPDATE jobs
            SET actual_apply_url = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE url = ?;
        """, (actual_apply_url, status, url))
        conn.commit()
        return cursor.rowcount > 0


def get_pending_apply_urls(db_path: str = DEFAULT_DB_PATH) -> List[str]:
    """Returns list of URLs that are still missing an apply link."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT url FROM jobs 
            WHERE actual_apply_url IS NULL OR actual_apply_url = '' OR status = 'pending_apply'
            ORDER BY created_at ASC;
        """).fetchall()
        return [row["url"] for row in rows]


def get_job_stats(db_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    """Returns count of total, completed, and pending jobs."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs;").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'completed';").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'pending_apply';").fetchone()[0]
        return {
            "total": total,
            "completed": completed,
            "pending_apply": pending
        }


def get_all_jobs(db_path: str = DEFAULT_DB_PATH, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetches all jobs from database, optionally filtered by status."""
    init_db(db_path)
    query = "SELECT * FROM jobs"
    params = []
    if status_filter:
        query += " WHERE status = ?"
        params.append(status_filter)
    query += " ORDER BY updated_at DESC;"

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        jobs = []
        for r in rows:
            try:
                schema_obj = json.loads(r["job_schema"]) if r["job_schema"] else {}
            except Exception:
                schema_obj = {}

            jobs.append({
                "url": r["url"],
                "title": r["title"],
                "company": r["company"],
                "location": r["location"],
                "date_posted": r["date_posted"],
                "actual_apply_url": r["actual_apply_url"],
                "status": r["status"],
                "job_schema": schema_obj,
                "created_at": r["created_at"],
                "updated_at": r["updated_at"]
            })
        return jobs


def export_jobs_to_json(
    filepath: str = "exported_jobs.json",
    status_filter: Optional[str] = "completed",
    db_path: str = DEFAULT_DB_PATH
) -> int:
    """
    Exports jobs from database to a clean JSON array file.
    Default filters only 'completed' jobs (both job data and apply link present).
    Pass status_filter=None to export all.
    """
    jobs = get_all_jobs(db_path=db_path, status_filter=status_filter)
    export_list = []

    for j in jobs:
        # Construct unified payload suitable for platform import
        item = dict(j["job_schema"]) if j["job_schema"] else {}
        item["_scraped_url"] = j["url"]
        item["actual_apply_url"] = j["actual_apply_url"]
        export_list.append(item)

    abs_path = os.path.abspath(filepath)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        json.dump(export_list, f, indent=2, ensure_ascii=False)

    return len(export_list)


def delete_job(url: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Deletes a single job by URL."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM jobs WHERE url = ?;", (url,))
        conn.commit()
        return cursor.rowcount > 0


def clear_all_jobs(db_path: str = DEFAULT_DB_PATH) -> int:
    """Clears all jobs from database."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM jobs;")
        conn.commit()
        return cursor.rowcount
