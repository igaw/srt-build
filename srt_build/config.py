"""Configuration management for srt-build."""

import os
import yaml
from logging import warning


# Global color class for terminal output
class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


# Default system configuration
system_config = {
    "base-build-path": os.path.expanduser("~/.cache/srt-build/build"),
    "base-tool-path": ".",
    "jobfiles-path": os.path.expanduser("~/.cache/srt-build/jobs"),
    "result-path": os.path.expanduser("~/.cache/srt-build/results"),
}

kernel_config = {}
machine_config = {}
rt_suites = []
suites = []


def load_config():
    """Load configuration from YAML file."""
    global system_config, kernel_config, machine_config, rt_suites, suites

    config_candidates = [
        os.path.join(os.path.dirname(__file__), "..", "config.yml"),
        os.path.join(os.getcwd(), "config.yml"),
        os.path.expanduser("~/.config/srt-build/config.yml"),
    ]

    loaded_cfg = {}
    for path in config_candidates:
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    try:
                        loaded_cfg = yaml.safe_load(f) or {}
                        break
                    except yaml.YAMLError as exc:
                        warning("failed to parse %s: %s", path, exc)
        except Exception as exc:
            warning("error while attempting to open %s: %s", path, exc)

    # Override in-file defaults if user config provides entries
    if "system_config" in loaded_cfg:
        system_config.update(loaded_cfg["system_config"])
    if "kernel_config" in loaded_cfg:
        kernel_config = loaded_cfg["kernel_config"]
    if "machine_config" in loaded_cfg:
        machine_config = loaded_cfg["machine_config"]
    if "rt_suites" in loaded_cfg:
        rt_suites = loaded_cfg["rt_suites"]
    if "suites" in loaded_cfg:
        suites = loaded_cfg["suites"]

    return system_config, kernel_config, machine_config, rt_suites, suites
