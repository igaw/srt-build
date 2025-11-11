import os
import subprocess
import sys


def test_lava_list_tests():
    """Test lava --list-tests functionality."""
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build-new")
    )
    assert os.path.exists(script_path), "srt-build-new script not found"
    
    result = subprocess.run(
        [sys.executable, script_path, "lava", "--list-tests"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path)
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
        os.path.join(os.path.dirname(__file__), "..", "srt-build-new")
    )
    
    result = subprocess.run(
        [sys.executable, script_path, "lava", "--list-tests", "--flavors", "rt"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path)
    )
    
    assert result.returncode == 0, f"Expected return code 0, got {result.returncode}"
    output = result.stdout + result.stderr
    
    assert "RT Flavor" in output
    assert "smoke" in output or "stress-ng" in output
    print("✓ --list-tests with --flavors works!")


def test_lava_show_jobs_requires_machine():
    """Test that --show-jobs requires machine argument."""
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build-new")
    )
    
    result = subprocess.run(
        [sys.executable, script_path, "lava", "--show-jobs"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path)
    )
    
    # Should exit with error
    assert result.returncode != 0, "Expected non-zero exit code without machine"
    output = result.stdout + result.stderr
    assert "machine argument is required" in output
    print("✓ --show-jobs correctly requires machine!")


def test_lava_show_jobs_with_machine():
    """Test lava --show-jobs with machine argument."""
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build-new")
    )
    
    # Use a machine from config.yml
    result = subprocess.run(
        [sys.executable, script_path, "lava", "bbb", "--show-jobs", 
         "--testsuites", "smoke"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path)
    )
    
    assert result.returncode == 0, f"Expected return code 0, got {result.returncode}"
    output = result.stdout + result.stderr
    
    # Check for expected content
    assert "Generating Job Definitions" in output or "Machine:" in output
    print("✓ --show-jobs with machine works!")


def test_lava_help_shows_new_flags():
    """Test that help shows new flags."""
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build-new")
    )
    
    result = subprocess.run(
        [sys.executable, script_path, "lava", "--help"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(script_path)
    )
    
    assert result.returncode == 0
    output = result.stdout + result.stderr
    
    assert "--list-tests" in output
    assert "--show-jobs" in output
    print("✓ New flags appear in help!")


if __name__ == "__main__":
    print("Running lava command extension tests...\n")
    
    try:
        test_lava_help_shows_new_flags()
        test_lava_list_tests()
        test_lava_list_tests_with_flavor()
        test_lava_show_jobs_requires_machine()
        test_lava_show_jobs_with_machine()
        
        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
