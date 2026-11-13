"""Every job template renders, for every board and flavor, to a job
whose inline test steps are shell lines (strings): a ": " in a plain
YAML scalar would turn a step into a mapping and break LAVA's run.sh."""

import os
from types import SimpleNamespace

import jinja2
import pytest
import yaml

from srt_build import config
from srt_build.helpers import (
    flavor_job_ctx,
    generate_job,
    job_templates,
    load_job_ctx,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
JOBS = os.path.join(ROOT, "jobs")
with open(os.path.join(ROOT, "config.yml")) as f:
    CFG = yaml.safe_load(f)
FLAVORS = [
    f
    for f in sorted(os.listdir(JOBS))
    if os.path.isdir(os.path.join(JOBS, f)) and f != "boards"
]


def _templates(flavor, job_ctx):
    """(template, job context) of every template of the flavor; of a
    template with a list (stress-ng) only its first item, the others
    differ only in the item."""
    for root, _, _ in os.walk(os.path.join(JOBS, flavor)):
        seen = set()
        for path, ctx in job_templates(root, job_ctx):
            if path not in seen:
                seen.add(path)
                yield path, ctx


def test_items_one_job_each(monkeypatch):
    """stress-ng.jinja2 makes one job per stressor in stress-ng.items,
    named after it and running it."""
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    board = "rpi3-64"
    ctx = SimpleNamespace(**{"hostname": board, **CFG["machine_config"][board]})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    flavor_job_ctx(ctx, "rt", job_ctx)
    jobs = [
        yaml.safe_load(generate_job(JOBS, p, c))
        for p, c in job_templates(os.path.join(JOBS, "rt", "stress-ng"), job_ctx)
    ]
    names = [j["job_name"].split()[0] for j in jobs]
    assert len(names) == len(set(names)) > 300
    assert names[0] == "stress-ng-access"
    params = jobs[0]["actions"][-2]["test"]["definitions"][0]["parameters"]
    assert params["BACKGROUND_CMD"] == "stress-ng -v --access 0"


@pytest.mark.parametrize("board", sorted(CFG["machine_config"]))
def test_smoke_job(monkeypatch, board):
    """`srt-build smoke`'s job (no flavor) gets the job context too: a
    template variable missing is an error, and an empty KLOG_OK would
    let the kernel-log check pass on anything (grep -vE "")."""
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    ctx = SimpleNamespace(**{"hostname": board, **CFG["machine_config"][board]})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    with pytest.raises(jinja2.UndefinedError):
        generate_job(JOBS, os.path.join(JOBS, "job-smoke-tests.jinja2"), job_ctx)
    flavor_job_ctx(ctx, "", job_ctx)
    job = generate_job(JOBS, os.path.join(JOBS, "job-smoke-tests.jinja2"), job_ctx)
    assert 'KLOG_OK=""' not in job


@pytest.mark.parametrize("board", sorted(CFG["machine_config"]))
@pytest.mark.parametrize("flavor", FLAVORS)
def test_steps_are_strings(monkeypatch, board, flavor):
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    mc = CFG["machine_config"][board]
    ctx = SimpleNamespace(**{"hostname": board, **mc})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", ctx.hostname + ".yaml"))
    job_ctx["tags"] = [ctx.hostname]
    flavor_job_ctx(ctx, flavor, job_ctx)
    for path, tctx in _templates(flavor, job_ctx):
        job = yaml.safe_load(generate_job(JOBS, path, tctx))
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
    for path, tctx in _templates(flavor, job_ctx):
        job = yaml.safe_load(generate_job(JOBS, path, tctx))
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
    for path, tctx in _templates(flavor, job_ctx):
        job = yaml.safe_load(generate_job(JOBS, path, tctx))
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
    for path, tctx in _templates("rt", job_ctx):
        job = yaml.safe_load(generate_job(JOBS, path, tctx))
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
    for path, tctx in _templates(flavor, job_ctx):
        job = yaml.safe_load(generate_job(JOBS, path, tctx))
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
    """rt's rtla-osnoise switches 6.12's fair server off before testing;
    the other tests, rt-isolcpus and newer kernels keep it (config.yml
    flavors)."""
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    board = "rpi3-64"
    ctx = SimpleNamespace(
        **{"hostname": board, "kernel_describe": kernel, **CFG["machine_config"][board]}
    )
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    flavor_job_ctx(ctx, flavor, job_ctx)
    switched = 0
    for path, tctx in _templates(flavor, job_ctx):
        job = yaml.safe_load(generate_job(JOBS, path, tctx))
        names = [
            d.get("name")
            for a in job["actions"]
            for d in (a.get("test") or {}).get("definitions") or []
        ]
        expected = off and job["job_name"].split()[0] == "rtla-osnoise"
        assert ("fair-server" in names) == expected, f"{path}: {names}"
        if expected:
            # Before the test it is for.
            assert names.index("fair-server") == 0, names
            switched += 1
    assert switched == (1 if off else 0)


@pytest.mark.parametrize(
    "duration,base,want", [(60, 7, 7), (900, 5, 22), (900, 7, 24), (3600, 7, 69)]
)
def test_job_timeout_covers_boot_and_test(duration, base, want):
    """A long test adds to the template's job timeout (boot and checks):
    job 718 (1 h test, bbb boot retry) ran out of time with duration +
    5 min."""
    from srt_build.helpers import _bump_job_timeouts

    job = {
        "timeouts": {
            "job": {"minutes": base},
            "action": {"minutes": 5},
            "connection": {"minutes": 5},
        }
    }
    _bump_job_timeouts(job, duration)
    assert job["timeouts"]["job"]["minutes"] == want
    assert job["timeouts"]["action"]["minutes"] * 60 >= min(duration + 120, 300)


def test_definitions_through_macro():
    """Test definitions from test-definitions come from
    test-definition.jinja2's macro, which adds what every one of them
    takes (repository, branch, Artifactorial): one place to change."""
    for root, _, files in os.walk(JOBS):
        for name in files:
            path = os.path.join(root, name)
            if not name.endswith(".jinja2") or name == "test-definition.jinja2":
                continue
            with open(path) as f:
                text = f.read()
            assert "test_definitions_url" not in text, path
            assert "ARTIFACTORIAL" not in text, path


@pytest.mark.parametrize("flavor", FLAVORS)
def test_definitions_without_history(monkeypatch, flavor):
    """test-definitions is cloned without .git: a combined job carries
    a dozen copies, three times over, on the LAVA server's disk (it ran
    full in round 12)."""
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    board = "rpi3-64"
    ctx = SimpleNamespace(**{"hostname": board, **CFG["machine_config"][board]})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    flavor_job_ctx(ctx, flavor, job_ctx)
    for path, tctx in _templates(flavor, job_ctx):
        job = yaml.safe_load(generate_job(JOBS, path, tctx))
        for action in job["actions"]:
            for d in (action.get("test") or {}).get("definitions") or []:
                if d.get("from") == "git" and "test-definitions" in str(
                    d.get("repository")
                ):
                    assert d.get("history") is False, (path, d["name"])


@pytest.mark.parametrize("rnd", [None, "13", "t3"])
def test_round_in_metadata(monkeypatch, rnd):
    """srt.round only in jobs of a round (`round start`); job-base has
    it only when the context has one (StrictUndefined)."""
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    board = "c2d"
    ctx = SimpleNamespace(
        **{"hostname": board, **CFG["machine_config"][board]},
        args=SimpleNamespace(round=rnd),
    )
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    flavor_job_ctx(ctx, "rt", job_ctx)
    for path, tctx in _templates("rt", job_ctx):
        md = yaml.safe_load(generate_job(JOBS, path, tctx))["metadata"]
        assert md.get("srt.round") == rnd
