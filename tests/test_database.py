#!/usr/bin/env python3
"""Test script to verify database functionality."""

import os
import sys
import tempfile

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from srt_build.database import (
    init_database,
    save_job_ids_to_db,
    get_jobs_from_db,
    get_job_list_from_db,
)


def test_database():
    """Test the database functionality."""
    print("Testing database functionality...")

    # Create temporary directory for test
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup test configuration
        test_config = {
            "database-path": os.path.join(tmpdir, "test_jobs.db"),
            "jobfiles-path": tmpdir,
        }

        # Test 1: Initialize database
        print("✓ Test 1: Initializing database...")
        init_database(test_config)
        assert os.path.exists(test_config["database-path"])
        print("  Database created successfully")

        # Test 2: Save job IDs
        print("✓ Test 2: Saving job IDs...")
        machine = "c2d"
        jobs = [167, 167]
        save_job_ids_to_db(machine, jobs, test_config)
        print(f"  Saved test suite {jobs[0]} with {len(jobs)} jobs")

        # Test 3: Save multiple job suites
        print("✓ Test 3: Saving multiple job suites...")
        jobs2 = [168, 168]
        save_job_ids_to_db(machine, jobs2, test_config)

        jobs3 = [181, 181, 182, 183, 184, 185, 186, 187, 188, 189,
                 190, 191, 192, 193, 194, 195]
        save_job_ids_to_db(machine, jobs3, test_config)
        print(f"  Saved test suite {jobs3[0]} with {len(jobs3)} jobs")

        # Test 4: Get single job (non-batch mode)
        print("✓ Test 4: Getting single job...")
        result = get_jobs_from_db(machine, 167, test_config, batch=False)
        assert result == [167], f"Expected [167], got {result}"
        print(f"  Retrieved: {result}")

        # Test 5: Get batch of jobs
        print("✓ Test 5: Getting batch of jobs...")
        result = get_jobs_from_db(machine, 181, test_config, batch=True)
        assert len(result) == 16, f"Expected 16 jobs, got {len(result)}"
        assert result[0] == 181, f"Expected first job 181, got {result[0]}"
        print(f"  Retrieved {len(result)} jobs: {result[:5]}...")

        # Test 6: Get job list
        print("✓ Test 6: Getting job list...")
        job_list = get_job_list_from_db(machine, test_config)
        assert len(job_list) == 3, f"Expected 3 suites, got {len(job_list)}"
        assert 167 in job_list and 168 in job_list and 181 in job_list
        print(f"  Retrieved suite IDs: {job_list}")

        # Test 7: Get jobs for different machine
        print("✓ Test 7: Testing machine isolation...")
        machine2 = "rpi3"
        jobs_rpi = [196, 196]
        save_job_ids_to_db(machine2, jobs_rpi, test_config)

        jobs_rpi2 = [197, 197]
        save_job_ids_to_db(machine2, jobs_rpi2, test_config)

        machine1_list = get_job_list_from_db(machine, test_config)
        machine2_list = get_job_list_from_db(machine2, test_config)
        assert len(machine1_list) == 3, "Machine c2d should have 3 suites"
        assert len(machine2_list) == 2, "Machine rpi3 should have 2 suites"
        print(f"  {machine}: {len(machine1_list)} suites")
        print(f"  {machine2}: {len(machine2_list)} suites")

        print("\n✅ All tests passed!")


if __name__ == "__main__":
    try:
        test_database()
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
