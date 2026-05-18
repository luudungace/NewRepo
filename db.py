from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATABASE_PATH
from url_filters import SOCIAL_MEDIA_ROOTS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn() -> sqlite3.Connection:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                status TEXT,
                total_urls INTEGER DEFAULT 0,
                crawled_urls INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS dorks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER,
                query TEXT,
                status TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER,
                dork TEXT,
                url TEXT,
                domain TEXT,
                title TEXT,
                emails TEXT,
                phones TEXT,
                status TEXT,
                error TEXT,
                crawled_at TEXT,
                UNIQUE(job_id, url)
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER,
                message TEXT,
                level TEXT,
                created_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_results_job_id ON results(job_id);
            CREATE INDEX IF NOT EXISTS idx_results_domain ON results(domain);
            CREATE INDEX IF NOT EXISTS idx_results_status ON results(status);
            CREATE INDEX IF NOT EXISTS idx_logs_job_id_id ON logs(job_id, id DESC);
            """
        )


def create_job(name: str) -> int:
    now = utc_now()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO jobs (name, status, total_urls, crawled_urls, success_count, failed_count, created_at, updated_at)
            VALUES (?, 'created', 0, 0, 0, 0, ?, ?)
            """,
            (name, now, now),
        )
        return int(cur.lastrowid)


def insert_dork(job_id: int, query: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO dorks (job_id, query, status, created_at) VALUES (?, ?, 'created', ?)",
            (job_id, query, utc_now()),
        )
        return int(cur.lastrowid)


def update_dork_status(job_id: int, query: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE dorks SET status = ? WHERE job_id = ? AND query = ?", (status, job_id, query))


def upsert_result(
    job_id: int,
    dork: str,
    url: str,
    domain: str,
    title: str,
    emails: str,
    phones: str,
    status: str,
    error: str,
    crawled_at: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO results (job_id, dork, url, domain, title, emails, phones, status, error, crawled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, url) DO UPDATE SET
                dork=excluded.dork,
                domain=excluded.domain,
                title=excluded.title,
                emails=excluded.emails,
                phones=excluded.phones,
                status=excluded.status,
                error=excluded.error,
                crawled_at=excluded.crawled_at
            """,
            (job_id, dork, url, domain, title, emails, phones, status, error, crawled_at),
        )


def _quality_filter_clause() -> tuple[str, list[Any]]:
    params: list[Any] = []
    social_parts = ["(domain = ? OR domain LIKE ?)" for _ in SOCIAL_MEDIA_ROOTS]
    for root in SOCIAL_MEDIA_ROOTS:
        params.extend([root, f"%.{root}"])
    social_sql = f"NOT ({' OR '.join(social_parts)})" if social_parts else "1=1"
    http_sql = "NOT (status = 'failed' AND error IN ('HTTP 403', 'HTTP 404'))"
    return f"({social_sql} AND {http_sql})", params


def _filters(
    job_id: int | None,
    search: str | None,
    status: str | None,
    *,
    quality_only: bool = True,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if job_id is not None:
        clauses.append("job_id = ?")
        params.append(job_id)
    if search:
        like = f"%{search.strip()}%"
        clauses.append("(domain LIKE ? OR emails LIKE ? OR phones LIKE ? OR status LIKE ? OR url LIKE ? OR title LIKE ?)")
        params.extend([like, like, like, like, like, like])
    if status and status != "all":
        clauses.append("status = ?")
        params.append(status)
    if quality_only:
        quality_sql, quality_params = _quality_filter_clause()
        clauses.append(quality_sql)
        params.extend(quality_params)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def get_results(
    job_id: int | None = None,
    search: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    *,
    quality_only: bool = True,
) -> list[dict[str, Any]]:
    where, params = _filters(job_id, search, status, quality_only=quality_only)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT job_id, dork, url, domain, title, emails, phones, status, error, crawled_at
            FROM results
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return [dict(row) for row in rows]


def count_results(
    job_id: int | None = None,
    search: str | None = None,
    status: str | None = None,
    *,
    quality_only: bool = True,
) -> int:
    where, params = _filters(job_id, search, status, quality_only=quality_only)
    with get_conn() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM results {where}", params).fetchone()[0])


def add_log(job_id: int, message: str, level: str = "INFO") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO logs (job_id, message, level, created_at) VALUES (?, ?, ?, ?)",
            (job_id, message, level, utc_now()),
        )


def get_logs(job_id: int, limit: int = 200) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT created_at, level, message
            FROM logs
            WHERE job_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (job_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def update_job_progress(
    job_id: int,
    *,
    status: str | None = None,
    total_urls: int | None = None,
    crawled_urls: int | None = None,
    success_count: int | None = None,
    failed_count: int | None = None,
) -> None:
    updates: list[str] = ["updated_at = ?"]
    params: list[Any] = [utc_now()]
    values = {
        "status": status,
        "total_urls": total_urls,
        "crawled_urls": crawled_urls,
        "success_count": success_count,
        "failed_count": failed_count,
    }
    for key, value in values.items():
        if value is not None:
            updates.append(f"{key} = ?")
            params.append(value)
    params.append(job_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", params)


def get_job(job_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
