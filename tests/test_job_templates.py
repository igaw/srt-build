"""Every job template renders, for every board and flavor, to a job
whose inline test steps are shell lines (strings): a ": " in a plain
YAML scalar would turn a step into a mapping and break LAVA's run.sh."""

import os
from types import SimpleNamespace

import pytest
import yaml

from srt_build import config
from srt_build.helpers import flavor_job_ctx, generate_job, load_job_ctx

ROOT = os.path.join(os.path.dirname(__file__), "..")
JOBS = os.path.join(ROOT, "jobs")
with open(os.path.join(ROOT, "config.yml")) as f:
    CFG = yaml.safe_load(f)
FLAVORS = [
    f
    for f in sorted(os.listdir(JOBS))
    if os.path.isdir(os.path.join(JOBS, f)) and f != "boards"
]


def _templates(flavor):
    for root, _, files in os.walk(os.path.join(JOBS, flavor)):
        if "stress-ng" in root:
            continue
        for name in sorted(files):
            if name.endswith(".jinja2"):
                yield os.path.join(root, name)


@pytest.mark.parametrize("board", sorted(CFG["machine_config"]))
@pytest.mark.parametrize("flavor", FLAVORS)
def test_steps_are_strings(monkeypatch, board, flavor):
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    mc = CFG["machine_config"][board]
    ctx = SimpleNamespace(**{"hostname": board, **mc})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", ctx.hostname + ".yaml"))
    job_ctx["tags"] = [ctx.hostname]
    flavor_job_ctx(ctx, flavor, job_ctx)
    for path in _templates(flavor):
        job = yaml.safe_load(generate_job(JOBS, path, job_ctx))
        for action in job["actions"]:
            for d in (action.get("test") or {}).get("definitions") or []:
                repo = d.get("repository")
                if not isinstance(repo, dict):  # a git URL, not inline
                    continue
                for step in repo.get("run", {}).get("steps", []):
                    assert isinstance(step, str), f"{path}: {step!r}"
