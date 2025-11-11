#!/usr/bin/env python3
"""
Quick test to verify --show-jobs works with machine argument
"""
import subprocess
import sys

print("=" * 80)
print("Testing: ./srt-build-new lava bbb --show-jobs --testsuites smoke")
print("=" * 80)

result = subprocess.run(
    [
        sys.executable,
        "srt-build-new",
        "lava",
        "bbb",
        "--show-jobs",
        "--testsuites",
        "smoke",
    ],
    cwd="/workspaces/srt-build",
    capture_output=True,
    text=True,
)

print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
print(f"\nExit code: {result.returncode}")

if result.returncode == 0:
    print("\n✓ SUCCESS: --show-jobs works with machine argument!")
else:
    print("\n✗ FAILED")
