#!/usr/bin/env python3
"""Test the --show-jobs functionality"""
import sys
sys.path.insert(0, '/workspaces/srt-build')

# Test 1: Show help
print("=" * 80)
print("TEST 1: Check --show-jobs flag is in help")
print("=" * 80)
sys.argv = ['srt-build-new', 'lava', '--help']
try:
    from srt_build.main import main
    main()
except SystemExit:
    pass

print("\n" + "=" * 80)
print("TEST 2: Try --show-jobs without machine (should fail)")
print("=" * 80)
sys.argv = ['srt-build-new', 'lava', '--show-jobs']
try:
    # Reload to reset state
    import importlib
    import srt_build.main
    importlib.reload(srt_build.main)
    from srt_build.main import main
    main()
except SystemExit as e:
    print(f"Exited with code: {e.code}")

print("\n" + "=" * 80)
print("TEST 3: Try --show-jobs with machine (smoke test)")
print("=" * 80)
print("Command: ./srt-build-new lava bbb --show-jobs --testsuites smoke")
print("(This would show generated jobs if board config exists)")
