#!/usr/bin/env python3
"""Test script to verify lava --list-tests functionality."""
import sys
import os

# Add the package to the path
sys.path.insert(0, "/workspaces/srt-build")

from srt_build.main import main

# Override sys.argv for testing
sys.argv = ["srt-build-new", "lava", "--list-tests"]

# Run the main function
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
