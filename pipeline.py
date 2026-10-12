import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "github_pipeline.db"

API_URL = "https://api.github.com/search/repositories"
SEARCH_QUERY = "data-engineering"
MAX_PAGES = 3
PER_PAGE = 100
MAX_RETRIES = 4


def initialize_database():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS raw_api_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            page INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            http_status INTEGER NOT NULL,
            response_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clean_repositories (
            repo_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            owner_login TEXT,
            description TEXT,
            language TEXT,
            stars INTEGER NOT NULL DEFAULT 0,
            forks INTEGER NOT NULL DEFAULT 0,
            open_issues INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            html_url TEXT,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS report_language_summary (
            language TEXT PRIMARY KEY,
            repository_count INTEGER NOT NULL,
            average_stars REAL NOT NULL,
            total_stars INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS report_top_repositories (
            repo_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            language TEXT,
            stars INTEGER NOT NULL,
            forks INTEGER NOT NULL,
            html_url TEXT
        );
        """)


def fetch_page(session, page):
    params = {
        "q": SEARCH_QUERY,
        "sort": "stars",
        "order": "desc",
        "per_page": PER_PAGE,
        "page": page,
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(
                API_URL, params=params, timeout=30
            )

            if response.status_code == 200:
                payload = response.json()

                if not isinstance(payload, dict) or not isinstance(
                    payload.get("items"), list
                ):
                    raise ValueError("Unexpected GitHub API response format")

                return response, payload

            rate_limited = (
                response.status_code in (403, 429)
                and (
                    response.status_code == 429
                    or response.headers.get("X-RateLimit-Remaining") == "0"
                    or "rate limit" in response.text.lower()
                )
            )

            retryable = (
                rate_limited
                or response.status_code in (500, 502, 503, 504)
            )

            if not retryable or attempt == MAX_RETRIES - 1:
                response.raise_for_status()

            retry_after = response.headers.get("Retry-After")

            if retry_after and retry_after.isdigit():
                wait = int(retry_after)
            elif rate_limited and response.headers.get(
                "X-RateLimit-Reset"
            ):
                wait = max(
                    1,
                    int(response.headers["X-RateLimit-Reset"])
                    - int(time.time()) + 1,
                )
            else:
                wait = min(30, 2 ** attempt)

            print(
                f"HTTP {response.status_code}; "
                f"retrying in {wait} seconds"
            )
            time.sleep(wait)

        except (requests.Timeout, requests.ConnectionError):
            if attempt == MAX_RETRIES - 1:
                raise

            wait = min(30, 2 ** attempt)
            print(f"Connection error; retrying in {wait} seconds")
            time.sleep(wait)

    raise RuntimeError(f"Unable to fetch page {page}")


def ingest():
    with requests.Session() as session:
        session.headers.update({
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-data-engineering-assignment",
        })

        for page in range(1, MAX_PAGES + 1):
            response, payload = fetch_page(session, page)
            fetched_at = datetime.now(timezone.utc).isoformat()

            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    INSERT INTO raw_api_responses
                    (query, page, fetched_at, http_status, response_json)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    SEARCH_QUERY,
                    page,
                    fetched_at,
                    response.status_code,
                    json.dumps(payload),
                ))

            items = payload["items"]
            print(f"Page {page}: fetched {len(items)} repositories")

            if len(items) < PER_PAGE:
                break


def transform():
    skipped = 0

    with sqlite3.connect(DB_PATH) as conn:
        raw_rows = conn.execute("""
            SELECT fetched_at, response_json
            FROM raw_api_responses
            WHERE query = ?
            ORDER BY id
        """, (SEARCH_QUERY,)).fetchall()

        for fetched_at, response_json in raw_rows:
            try:
                payload = json.loads(response_json)
            except (json.JSONDecodeError, TypeError):
                skipped += 1
                continue

            for repo in payload.get("items", []):
                repo_id = repo.get("id")
                full_name = repo.get("full_name")

                if repo_id is None or not full_name:
                    skipped += 1
                    continue

                conn.execute("""
                    INSERT INTO clean_repositories (
                        repo_id, full_name, owner_login, description,
                        language, stars, forks, open_issues,
                        created_at, updated_at, html_url, fetched_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(repo_id) DO UPDATE SET
                        full_name = excluded.full_name,
                        owner_login = excluded.owner_login,
                        description = excluded.description,
                        language = excluded.language,
                        stars = excluded.stars,
                        forks = excluded.forks,
                        open_issues = excluded.open_issues,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        html_url = excluded.html_url,
                        fetched_at = excluded.fetched_at
                """, (
                    repo_id,
                    full_name,
                    (repo.get("owner") or {}).get("login"),
                    repo.get("description"),
                    repo.get("language"),
                    repo.get("stargazers_count") or 0,
                    repo.get("forks_count") or 0,
                    repo.get("open_issues_count") or 0,
                    repo.get("created_at"),
                    repo.get("updated_at"),
                    repo.get("html_url"),
                    fetched_at,
                ))

        # Rebuild reporting tables from the current clean layer.
        conn.execute("DELETE FROM report_language_summary")
        conn.execute("DELETE FROM report_top_repositories")

        conn.execute("""
            INSERT INTO report_language_summary
            SELECT
                COALESCE(language, 'Unknown'),
                COUNT(*),
                ROUND(AVG(stars), 1),
                SUM(stars)
            FROM clean_repositories
            GROUP BY COALESCE(language, 'Unknown')
        """)

        conn.execute("""
            INSERT INTO report_top_repositories
            SELECT repo_id, full_name, language, stars, forks, html_url
            FROM clean_repositories
            ORDER BY stars DESC, full_name
            LIMIT 10
        """)

        count = conn.execute(
            "SELECT COUNT(*) FROM clean_repositories"
        ).fetchone()[0]

    print(f"Unique repositories in clean layer: {count}")
    print(f"Records skipped: {skipped}")


def main():
    initialize_database()
    ingest()
    transform()
    print(f"Pipeline complete. Database: {DB_PATH}")


if __name__ == "__main__":
    main()
