#!/usr/bin/env python3
"""
Standalone test for lava command extensions
Run this from the repository root: python3 test_lava_features.py
"""
import os
import sys

# Add the package to path
sys.path.insert(0, "/workspaces/srt-build")

print("=" * 80)
print("Testing LAVA Command Extensions")
print("=" * 80)

# Test 1: Import the module
print("\n[1/5] Testing module import...")
try:
    from srt_build.commands import cmd_lava

    print("✓ Module imports successfully")
except Exception as e:
    print(f"✗ Failed to import: {e}")
    sys.exit(1)

# Test 2: Check functions exist
print("\n[2/5] Testing new functions exist...")
try:
    assert hasattr(cmd_lava, "list_available_tests"), "list_available_tests not found"
    assert hasattr(cmd_lava, "show_generated_jobs"), "show_generated_jobs not found"
    assert hasattr(cmd_lava, "extract_test_name"), "extract_test_name not found"
    print("✓ All new functions exist")
except AssertionError as e:
    print(f"✗ {e}")
    sys.exit(1)

# Test 3: Test extract_test_name function
print("\n[3/5] Testing extract_test_name...")
try:
    # Test with a real file
    test_file = "/workspaces/srt-build/jobs/rt/smoke/0005-cyclictest.jinja2"
    if os.path.exists(test_file):
        name = cmd_lava.extract_test_name(test_file, "0005-cyclictest.jinja2")
        assert name == "cyclictest", f"Expected 'cyclictest', got '{name}'"
        print(f"✓ Extracted name correctly: '{name}'")
    else:
        print("⚠ Test file not found, skipping")
except Exception as e:
    print(f"✗ Failed: {e}")
    sys.exit(1)

# Test 4: Check if job path exists
print("\n[4/5] Testing job path structure...")
try:
    job_path = "/workspaces/srt-build/jobs"
    assert os.path.exists(job_path), "Jobs directory not found"

    # Check for flavor directories
    flavors = ["rt", "nohz", "ll", "up", "vp", "none"]
    found_flavors = [f for f in flavors if os.path.exists(os.path.join(job_path, f))]
    assert len(found_flavors) > 0, "No flavor directories found"
    print(
        f"✓ Found {len(found_flavors)} flavor directories: {', '.join(found_flavors)}"
    )
except Exception as e:
    print(f"✗ Failed: {e}")
    sys.exit(1)

# Test 5: Count available tests
print("\n[5/5] Counting available tests...")
try:
    total_tests = 0
    for flavor in ["rt", "nohz", "ll", "up", "vp", "none"]:
        flavor_path = os.path.join(job_path, flavor)
        if not os.path.exists(flavor_path):
            continue

        for item in os.listdir(flavor_path):
            item_path = os.path.join(flavor_path, item)
            if os.path.isdir(item_path):
                test_files = [f for f in os.listdir(item_path) if f.endswith(".jinja2")]
                total_tests += len(test_files)

    print(f"✓ Found {total_tests} test templates across all flavors")
    assert total_tests > 0, "No test templates found"
except Exception as e:
    print(f"✗ Failed: {e}")
    sys.exit(1)

print("\n" + "=" * 80)
print("✓ ALL TESTS PASSED")
print("=" * 80)

print("\nFeatures ready to use:")
print("  1. ./srt-build-new lava --list-tests")
print("  2. ./srt-build-new lava <machine> --show-jobs --testsuites <suite>")
