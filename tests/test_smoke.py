import os
import subprocess
import sys


def test_srt_build_help():
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "srt-build")
    )
    assert os.path.exists(script_path), "srt-build script not found at repository root"
    result = subprocess.run(
        [sys.executable, script_path, "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0, f"Expected return code 0, got {result.returncode}"
    output = (result.stdout + result.stderr).strip()
    assert output, "Expected usage/help output from srt-build --help"
