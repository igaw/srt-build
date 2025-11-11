"""Database management for LAVA job tracking."""

import sqlite3
import os
from typing import List, Optional
from logging import debug, error


def get_db_path(system_config):
    """Get the database file path from system configuration."""
    default_path = os.path.expanduser("~/.cache/srt-build/jobs.db")
    return system_config.get("database-path", default_path)


def init_database(system_config):
    """Initialize the SQLite database with required tables.

    Schema:
    - test_suites: Each row represents a test suite run with primary job ID
    - jobs: Individual job IDs associated with each test suite
    """
    db_path = get_db_path(system_config)

    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create test_suites table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_suites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suite_id INTEGER NOT NULL,
            machine TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        )
    """)

    # Create jobs table to store individual job IDs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_suite_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            FOREIGN KEY (test_suite_id) REFERENCES test_suites(id)
        )
    """)

    # Create index for faster lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_machine
        ON test_suites(machine)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_suite_id
        ON test_suites(suite_id)
    """)

    conn.commit()
    conn.close()
    debug(f"Database initialized at {db_path}")


def save_job_ids_to_db(
    machine: str,
    jobs: List[int],
    system_config,
    metadata: Optional[str] = None
):
    """Save a test suite and its job IDs to the database.

    Args:
        machine: Target machine name
        jobs: List of job IDs, where jobs[0] is the suite ID
        system_config: System configuration dictionary
        metadata: Optional metadata string
    """
    if not jobs:
        debug("No jobs to save")
        return

    db_path = get_db_path(system_config)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Insert test suite
        suite_id = jobs[0]
        cursor.execute("""
            INSERT INTO test_suites (suite_id, machine, metadata)
            VALUES (?, ?, ?)
        """, (suite_id, machine, metadata))

        test_suite_pk = cursor.lastrowid

        # Insert all job IDs
        for job_id in jobs:
            cursor.execute("""
                INSERT INTO jobs (test_suite_id, job_id)
                VALUES (?, ?)
            """, (test_suite_pk, job_id))

        conn.commit()
        msg = f"Saved test suite {suite_id} with {len(jobs)} jobs"
        debug(f"{msg} for machine {machine}")
    except Exception as exc:
        error(f"Error saving jobs to database: {exc}")
        conn.rollback()
    finally:
        conn.close()


def get_jobs_from_db(
    machine: str,
    job_id: int,
    system_config,
    batch: bool = False
) -> List[int]:
    """Get list of job IDs from the database.

    Args:
        machine: Target machine name
        job_id: The suite ID to look up
        system_config: System configuration dictionary
        batch: If True, return all jobs; if False, return only job_id

    Returns:
        List of job IDs
    """
    if not batch:
        return [int(job_id)]

    db_path = get_db_path(system_config)

    if not os.path.exists(db_path):
        debug(f"Database not found at {db_path}")
        return [int(job_id)]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Find the test suite
        cursor.execute("""
            SELECT id FROM test_suites
            WHERE machine = ? AND suite_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (machine, job_id))

        result = cursor.fetchone()
        if not result:
            msg = f"No test suite found for machine {machine}"
            debug(f"{msg} with suite_id {job_id}")
            return [int(job_id)]

        test_suite_pk = result[0]

        # Get all jobs for this test suite
        cursor.execute("""
            SELECT job_id FROM jobs
            WHERE test_suite_id = ?
            ORDER BY id
        """, (test_suite_pk,))

        jobs = [row[0] for row in cursor.fetchall()]
        return jobs if jobs else [int(job_id)]

    except Exception as exc:
        error(f"Error reading jobs from database: {exc}")
        return [int(job_id)]
    finally:
        conn.close()


def get_job_list_from_db(machine: str, system_config) -> List[int]:
    """Get all test suite IDs for a machine.

    Args:
        machine: Target machine name
        system_config: System configuration dictionary

    Returns:
        List of suite IDs (the primary job ID for each test suite)
    """
    db_path = get_db_path(system_config)

    if not os.path.exists(db_path):
        debug(f"Database not found at {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT suite_id FROM test_suites
            WHERE machine = ?
            ORDER BY created_at
        """, (machine,))

        jobs = [row[0] for row in cursor.fetchall()]
        return jobs

    except Exception as exc:
        error(f"Error reading job list from database: {exc}")
        return []
    finally:
        conn.close()
