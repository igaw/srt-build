import os
import subprocess
import sys


def test_lava_list_tests():
    """Test lava --list-tests functionality."""
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build")
    )
    assert os.path.exists(script_path), "srt-build script not found"

    result = subprocess.run(
        [sys.executable, script_path, "lava", "--list-tests"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path),
    )

    assert result.returncode == 0, f"Expected return code 0, got {result.returncode}"
    output = result.stdout + result.stderr

    # Check for expected content
    assert "Available Test Suites and Tests" in output
    assert "RT Flavor" in output or "NOHZ Flavor" in output
    assert "Test Suite:" in output
    print("✓ --list-tests works!")


def test_lava_list_tests_with_flavor():
    """Test lava --list-tests with flavor filter."""
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build")
    )

    result = subprocess.run(
        [sys.executable, script_path, "lava", "--list-tests", "--flavors", "rt"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path),
    )

    assert result.returncode == 0, f"Expected return code 0, got {result.returncode}"
    output = result.stdout + result.stderr

    assert "RT Flavor" in output
    assert "smoke" in output or "stress-ng" in output
    print("✓ --list-tests with --flavors works!")


def test_lava_show_jobs_requires_machine():
    """Test that --show-jobs requires machine argument."""
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build")
    )

    result = subprocess.run(
        [sys.executable, script_path, "lava", "--show-jobs"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path),
    )

    # Should exit with error
    assert result.returncode != 0, "Expected non-zero exit code without machine"
    output = result.stdout + result.stderr
    assert "machine argument is required" in output
    print("✓ --show-jobs correctly requires machine!")


def test_lava_show_jobs_with_machine():
    """Test lava --show-jobs with machine argument."""
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build")
    )

    # Use a machine from config.yml
    result = subprocess.run(
        [
            sys.executable,
            script_path,
            "lava",
            "bbb",
            "--show-jobs",
            "--testsuites",
            "smoke",
        ],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path),
    )

    assert result.returncode == 0, f"Expected return code 0, got {result.returncode}"
    output = result.stdout + result.stderr

    # Check for expected content
    assert "Generating Job Definitions" in output or "Machine:" in output
    print("✓ --show-jobs with machine works!")


def test_lava_help_shows_new_flags():
    """Test that help shows new flags."""
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build")
    )

    result = subprocess.run(
        [sys.executable, script_path, "lava", "--help"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path),
    )

    assert result.returncode == 0
    output = result.stdout + result.stderr

    assert "--list-tests" in output
    assert "--show-jobs" in output
    print("✓ New flags appear in help!")


def test_extract_test_name():
    """The job name comes from the template's job_name, not its file name."""
    from srt_build.commands.cmd_lava import extract_test_name

    path = os.path.join(
        os.path.dirname(__file__), "..", "jobs", "rt", "smoke", "0005-cyclictest.jinja2"
    )
    assert extract_test_name(path, "0005-cyclictest.jinja2") == "cyclictest"
    assert extract_test_name("/nonexistent", "0001-foo.jinja2") == "0001-foo"
