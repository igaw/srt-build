#!/usr/bin/env python3
"""Quick test of the lava --list-tests functionality"""
import sys
import os

# Add the parent directory to the path
sys.path.insert(0, '/workspaces/srt-build')

# Override sys.argv
sys.argv = ['srt-build-new', 'lava', '--list-tests']

# Import and run
from srt_build.main import main

try:
    main()
    print("\n✓ Test passed!")
except Exception as e:
    print(f"\n✗ Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
