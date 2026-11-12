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


@pytest.mark.parametrize("board", sorted(CFG["machine_config"]))
@pytest.mark.parametrize("flavor", FLAVORS)
def test_kernel_log_checked(monkeypatch, board, flavor):
    """job-base appends the kernel-log check to every job: LAVA itself
    only catches splats while booting."""
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    mc = CFG["machine_config"][board]
    ctx = SimpleNamespace(**{"hostname": board, **mc})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", ctx.hostname + ".yaml"))
    job_ctx["tags"] = [ctx.hostname]
    flavor_job_ctx(ctx, flavor, job_ctx)
    for path in _templates(flavor):
        job = yaml.safe_load(generate_job(JOBS, path, job_ctx))
        last = job["actions"][-1].get("test") or {}
        names = [d.get("name") for d in last.get("definitions") or []]
        assert names == ["kernel-log"], f"{path}: {names}"


@pytest.mark.parametrize("flavor", FLAVORS)
def test_metadata(monkeypatch, flavor):
    """Every job says what it is, for `jobs export`: the test without the
    flavor that job_name has in it."""
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    board = "rpi3-64"
    ctx = SimpleNamespace(**{"hostname": board, **CFG["machine_config"][board]})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    flavor_job_ctx(ctx, flavor, job_ctx)
    for path in _templates(flavor):
        job = yaml.safe_load(generate_job(JOBS, path, job_ctx))
        md = job["metadata"]
        assert md["srt.board"] == board
        assert md["srt.flavor"] == flavor
        assert md["srt.test"] == job["job_name"].split()[0]
        assert md["srt.build"]


@pytest.mark.parametrize("board", sorted(CFG["machine_config"]))
def test_boot_retry(monkeypatch, board):
    """bbb boots again when U-Boot misses its PHY, with the job timeout
    grown for it; the other boards boot once."""
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    ctx = SimpleNamespace(**{"hostname": board, **CFG["machine_config"][board]})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    flavor_job_ctx(ctx, "rt", job_ctx)
    for path in _templates("rt"):
        job = yaml.safe_load(generate_job(JOBS, path, job_ctx))
        boot = next(a["boot"] for a in job["actions"] if "boot" in a)
        if board == "bbb":
            assert boot["failure_retry"] == 2
            assert job["timeouts"]["job"] == {"minutes": 7}
        else:
            assert "failure_retry" not in boot
            assert job["timeouts"]["job"] == {"minutes": 5}


@pytest.mark.parametrize("flavor", FLAVORS)
def test_steps_are_no_console_findings(monkeypatch, flavor):
    """LAVA echoes each step to the console, which `jobs report` scans:
    a step must not look like a kernel problem (the kernel-log check's
    own patterns did, in round 6)."""
    from srt_build.report import scan_console

    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    board = "rpi3-64"
    ctx = SimpleNamespace(**{"hostname": board, **CFG["machine_config"][board]})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    flavor_job_ctx(ctx, flavor, job_ctx)
    for path in _templates(flavor):
        job = yaml.safe_load(generate_job(JOBS, path, job_ctx))
        for action in job["actions"]:
            for d in (action.get("test") or {}).get("definitions") or []:
                repo = d.get("repository")
                if isinstance(repo, dict):
                    steps = ["+ " + s for s in repo.get("run", {}).get("steps", [])]
                    assert scan_console(steps) == [], f"{path}: {steps}"


@pytest.mark.parametrize(
    "flavor, kernel, off",
    [
        ("rt", "v6.12.117-rt23", True),
        ("rt", "v6.18.2-rt3", False),
        ("rt-isolcpus", "v6.12.117-rt23", False),
    ],
)
def test_fair_server_off(monkeypatch, flavor, kernel, off):
    """The rt flavor switches 6.12's fair server off before testing; its
    rt-isolcpus jobs and newer kernels keep it (config.yml flavors)."""
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    board = "rpi3-64"
    ctx = SimpleNamespace(
        **{"hostname": board, "kernel_describe": kernel, **CFG["machine_config"][board]}
    )
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    flavor_job_ctx(ctx, flavor, job_ctx)
    for path in _templates(flavor):
        job = yaml.safe_load(generate_job(JOBS, path, job_ctx))
        names = [
            d.get("name")
            for a in job["actions"]
            for d in (a.get("test") or {}).get("definitions") or []
        ]
        # pi-stress needs it: its busy loops starve everything else.
        expected = off and "pi-stress" not in path
        assert ("fair-server" in names) == expected, f"{path}: {names}"
        if expected:
            # Before the test it is for.
            assert names.index("fair-server") == 0, names
