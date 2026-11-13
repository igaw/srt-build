"""combined: one job running a flavor's tests in order (config.yml
flavors: combined), built from the same templates as the per-test
jobs."""

import os
from types import SimpleNamespace

import pytest
import yaml

from srt_build import combined, config
from srt_build.helpers import flavor_job_ctx, load_job_ctx

ROOT = os.path.join(os.path.dirname(__file__), "..")
JOBS = os.path.join(ROOT, "jobs")
with open(os.path.join(ROOT, "config.yml")) as f:
    CFG = yaml.safe_load(f)
COMBINED = [
    f for f, c in (CFG.get("flavors") or {}).items() if (c or {}).get("combined")
]


def _build(monkeypatch, board, flavor, kernel="v6.12.117-rt23"):
    monkeypatch.setattr(config, "flavors", CFG.get("flavors") or {})
    mc = CFG["machine_config"][board]
    ctx = SimpleNamespace(**{"hostname": board, "kernel_describe": kernel, **mc})
    job_ctx = load_job_ctx(os.path.join(JOBS, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    flavor_job_ctx(ctx, flavor, job_ctx)
    rendered = combined.render_templates(
        JOBS, os.path.join(JOBS, flavor, "smoke"), job_ctx
    )
    tests = combined.entries(CFG["flavors"][flavor])
    return combined.build(rendered, tests, flavor), tests


def _definitions(job):
    return [d for a in job["actions"] if "test" in a for d in a["test"]["definitions"]]


@pytest.mark.parametrize("flavor", COMBINED)
@pytest.mark.parametrize("board", ["c2d", "rpi3-64"])
def test_tests_in_order_each_checked(monkeypatch, board, flavor):
    job, tests = _build(monkeypatch, board, flavor)
    names = [
        d["name"]
        for d in _definitions(job)
        if d["name"] not in ("kernel-log", "fair-server", "fair-server-on")
        and not d["name"].startswith("kernel-log-")
    ]
    want = []
    for t, _ in tests:
        want.append(t)
    # definition names: the template's definition, not its job_name
    assert len(names) == len(want)
    # one boot, one deploy
    assert sum("boot" in a for a in job["actions"]) == 1
    assert sum("deploy" in a for a in job["actions"]) == 1
    # every test is followed by a kernel log check
    kinds = [
        _definitions({"actions": [a]})[0]["name"] for a in job["actions"] if "test" in a
    ]
    for i, k in enumerate(kinds):
        if k in ("fair-server", "settle", "fair-server-on"):
            continue
        if k == "kernel-log" or k.startswith("kernel-log-"):
            continue
        rest = [x for x in kinds[i + 1 :] if x != "fair-server-on"]
        assert rest and rest[0] == f"kernel-log-{k}", kinds


@pytest.mark.parametrize("flavor", COMBINED)
@pytest.mark.parametrize("board", ["bbb", "c2d", "rpi3-32", "rpi3-64"])
def test_definition_names_unique(monkeypatch, board, flavor):
    # LAVA rejects a job whose test definitions share a name (job 793)
    job, _ = _build(monkeypatch, board, flavor)
    names = [d["name"] for d in _definitions(job)]
    assert len(names) == len(set(names)), names
    paths = [d["path"] for d in _definitions(job) if d.get("from") == "inline"]
    assert len(paths) == len(set(paths)), paths


def test_rt_durations_and_timeouts(monkeypatch):
    job, _ = _build(monkeypatch, "bbb", "rt")
    durations = {
        d["name"]: d["parameters"]["DURATION"]
        for d in _definitions(job)
        if d.get("from") == "git"
    }
    assert durations["rtla-timerlat"] == "5m"
    assert durations["rtla-osnoise"] == "5m"
    assert durations["rtla-timerlat-stress"] == "5m"
    assert durations["cyclictest"] == "1m"
    # pi-stress has a boot of its own
    assert "pi-stress" not in durations
    for a in job["actions"]:
        if "test" in a:
            to = a["test"]["timeout"]
            secs = to.get("seconds", 0) + 60 * to.get("minutes", 0)
            d = combined._main_definition(a)
            if d and d["name"].startswith("rtla"):
                assert secs >= 300 + 60
    t = job["timeouts"]
    assert t["connection"]["minutes"] * 60 > 300
    # bbb's template allows 7 min for deploy and boot; then 3 x 5 min,
    # 8 x 1 min plus slack per test
    assert t["job"]["minutes"] > 7 + 15 + 8
    assert job["metadata"]["srt.test"] == "combined"


def test_fair_server_back_on_after_osnoise(monkeypatch):
    job, _ = _build(monkeypatch, "c2d", "rt")
    names = [
        _definitions({"actions": [a]})[0]["name"] for a in job["actions"] if "test" in a
    ]
    i = names.index("rtla-osnoise")
    assert names[i - 1] == "fair-server"
    assert names[i + 1] == "fair-server-on"
    assert names.count("fair-server") == 1


def test_no_fair_server_on_other_kernels(monkeypatch):
    job, _ = _build(monkeypatch, "c2d", "rt", kernel="v6.18.1-rt1")
    names = [d["name"] for d in _definitions(job)]
    assert "fair-server" not in names and "fair-server-on" not in names


def test_unknown_test_is_an_error():
    with pytest.raises(ValueError):
        combined.build({}, [("cyclictest", None)], "rt")
