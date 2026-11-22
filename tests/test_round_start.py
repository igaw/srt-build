"""round start, round rerun and a plain lava command (a test round),
on fakes: nothing is submitted to a real LAVA."""

import os
from types import SimpleNamespace

import pytest
import yaml

import lava_fake
from srt_build import archive, config, helpers
from srt_build.commands import cmd_round_report, cmd_round_start

ROOT = os.path.join(os.path.dirname(__file__), "..")
with open(os.path.join(ROOT, "config.yml")) as f:
    CFG = yaml.safe_load(f)


@pytest.fixture
def lab(tmp_path, monkeypatch, deleted):
    monkeypatch.setattr(config, "flavors", CFG["flavors"])
    monkeypatch.setattr(config, "rounds", {
        "boards": ["c2d"],
        "submissions": [{}, {"flavors": ["rt"], "testsuites": "stress-ng-class"}],
    })  # fmt: skip
    monkeypatch.setattr(helpers, "run_cmd", lambda cmd, cwd=None: (0, "v6.12.117-rt23"))
    monkeypatch.setattr(cmd_round_start, "kernel_describe", lambda: "v6.12.117-rt23")
    monkeypatch.setattr(cmd_round_start, "checkout_warnings", lambda **kw: [])
    monkeypatch.setattr(cmd_round_start, "lava_free_gb", lambda c: 30)
    monkeypatch.setattr(helpers, "ensure_lavacli_available", lambda: None)
    submitted = []

    def fake_submit(path, jobs):
        with open(path) as f:
            submitted.append(yaml.safe_load(f))
        jobs.append(str(2000 + len(submitted)))

    monkeypatch.setattr(helpers, "_submit", fake_submit)
    lava = lava_fake.FakeLava([])
    for mod in (cmd_round_report, cmd_round_start):
        monkeypatch.setattr(mod.LavaApi, "from_config", classmethod(lambda c, s: lava))
    monkeypatch.setattr(archive, "fetch_url", lava_fake.upload)
    cfg = {
        "round-archive": str(tmp_path / "rounds"),
        "jobfiles-path": str(tmp_path / "jobfiles"),
        "base-build-path": str(tmp_path / "build"),
        "base-tool-path": ROOT,
        "lava-instance": "lava.test",
        "artifactorial-token": "FAKE-UPLOAD-TOKEN",
    }
    machines = CFG["machine_config"]
    return SimpleNamespace(cfg=cfg, top=tmp_path / "rounds", lava=lava,
                           submitted=submitted, machines=machines)  # fmt: skip


def start(lab, **kw):
    args = {"boards": None, "round": None, "test": False, "notes": None}
    args = {**args, "dry_run": False, "yes": False, "skip_build": True}
    args = SimpleNamespace(**{**args, **kw})
    cmd_round_start.cmd_round_start(args, lab.cfg, lab.machines, {})


def test_dry_run_submits_nothing(lab, capsys):
    start(lab, dry_run=True)
    out = capsys.readouterr().out
    assert "would submit: c2d rt rt-tests" in out
    assert "would submit: c2d rt stress-ng-io" in out
    assert lab.submitted == []
    assert archive.round_ids(str(lab.top)) == []


def test_start(lab, capsys):
    start(lab, notes="first")
    info = archive.load_round(str(lab.top), "1")
    assert info["kind"] == "release" and info["notes"] == "first"
    assert info["srt_build"] and info["kernel"] == "v6.12.117-rt23"
    assert info["submissions"][1] == {
        "flavors": ["rt"],
        "testsuites": "stress-ng-class",
    }
    ids = sorted(info["jobs"])
    assert ids == list(range(2001, 2001 + len(lab.submitted)))
    assert all(j["metadata"]["srt.round"] == "1" for j in lab.submitted)
    entries = info["jobs"]
    assert entries[2001] == {"board": "c2d", "flavor": "rt", "test": "rt-tests",
                             "submission": 0}  # fmt: skip
    assert {e["submission"] for e in entries.values()} == {0, 1}
    assert "2001  c2d  rt  rt-tests" in capsys.readouterr().out
    # The next one is 2, a test round t1.
    start(lab, test=True, boards="c2d")
    assert archive.round_ids(str(lab.top)) == ["1", "t1"]
    assert all(j["metadata"]["srt.round"] == "t1" for j in lab.submitted[len(ids) :])


def test_start_refuses_job_ids_of_another_round(lab):
    start(lab)
    n = len(lab.submitted)
    lab.submitted.clear()  # LAVA was reset: the same ids again
    with pytest.raises(SystemExit, match="was LAVA reset"):
        start(lab)
    assert n


def test_warnings_ask(lab, monkeypatch):
    monkeypatch.setattr(cmd_round_start, "checkout_warnings",
                        lambda **kw: ["srt-build is 2 commits behind"])  # fmt: skip
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("n\n"))
    with pytest.raises(SystemExit, match="nothing submitted"):
        start(lab)
    assert lab.submitted == []


class FakeRpc:
    def __init__(self, new):
        self.new = new
        self.definitions = []
        self.scheduler = SimpleNamespace(jobs=self)

    def submit(self, definition):
        self.definitions.append(definition)
        return [self.new]


def imported(lab, ids=(1, 2, 3)):
    for j in ids:
        lab.lava.jobs[j] = lava_fake.job(j, "bbb" if j < 3 else "c2d", round="12")
    args = SimpleNamespace(round="12", ids=",".join(map(str, ids)))
    cmd_round_report.cmd_round_import(args, lab.cfg, {})


def test_rerun(lab, monkeypatch):
    imported(lab)
    rpc = FakeRpc(4)
    monkeypatch.setattr(cmd_round_start, "rpc_from_lavacli", lambda **kw: rpc)
    cmd_round_start.cmd_round_rerun(SimpleNamespace(round="12", job=2), lab.cfg, {})
    assert rpc.definitions == [lab.lava.jobs[2]["definition"]]  # unchanged
    info = archive.load_round(str(lab.top), "12")
    assert info["reruns"] == {2: 4} and info["jobs"][4] == info["jobs"][2]
    assert "reported" not in info
    assert archive.counted_jobs(info) == [1, 3, 4]
    with pytest.raises(SystemExit, match="replaced by 4"):
        cmd_round_start.cmd_round_rerun(SimpleNamespace(round="12", job=2), lab.cfg, {})
    # A new id LAVA already gave to this round: refused.
    monkeypatch.setattr(cmd_round_start, "rpc_from_lavacli", lambda **kw: FakeRpc(1))
    with pytest.raises(SystemExit):
        cmd_round_start.cmd_round_rerun(SimpleNamespace(round="12", job=3), lab.cfg, {})


def test_checkout_warnings(tmp_path):
    import subprocess

    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True,
                       capture_output=True)  # fmt: skip

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
        "--allow-empty", "-m", "x")  # fmt: skip
    (tmp_path / "f").write_text("x")
    w = cmd_round_start.checkout_warnings(str(tmp_path), fetch=False)
    assert w == [
        "the srt-build checkout has local changes",
        "the srt-build checkout has no upstream",
    ]


def test_a_lava_command_is_a_test_round(lab, monkeypatch, capsys):
    """`srt-build lava c2d --skip-build`: a test round of its own,
    round.yaml written before the first job, every job tagged."""
    from srt_build.commands import cmd_lava
    from srt_build.main import create_parser

    monkeypatch.setattr(cmd_lava, "ensure_lavacli_available", lambda: None)
    seen = []

    def fake_submit(path, jobs):
        seen.append(archive.round_ids(str(lab.top)))  # already there
        with open(path) as f:
            lab.submitted.append(yaml.safe_load(f))
        jobs.append(str(3000 + len(lab.submitted)))

    monkeypatch.setattr(helpers, "_submit", fake_submit)

    def lava(*argv):
        args = create_parser().parse_args(["lava", "c2d", "--skip-build", *argv])
        ctx = helpers.Context(args, lab.machines, lab.cfg)
        return cmd_lava.cmd_lava(ctx, lab.cfg, {})

    ids = lava()
    assert seen[0] == ["t1"]
    info = archive.load_round(str(lab.top), "t1")
    assert info["kind"] == "test" and info["boards"] == ["c2d"]
    assert info["submissions"] == [{}]
    assert sorted(info["jobs"]) == ids == list(range(3001, 3001 + len(ids)))
    assert all(j["metadata"]["srt.round"] == "t1" for j in lab.submitted)
    out = capsys.readouterr().out
    assert "round t1 (test)" in out and f"{ids[-1]}  c2d" in out

    n = len(lab.submitted)
    ids2 = lava("--flavors", "rt", "--testsuites", "stress-ng-class")
    info2 = archive.load_round(str(lab.top), "t2")
    assert info2["submissions"] == [
        {"flavors": ["rt"], "testsuites": "stress-ng-class"}
    ]
    assert sorted(info2["jobs"]) == ids2
    assert all(j["metadata"]["srt.round"] == "t2" for j in lab.submitted[n:])

    # jobs results / cancel: the board's runs come from the archive.
    ctx = SimpleNamespace(args=SimpleNamespace(machine="c2d"))
    assert helpers.get_job_list(ctx, lab.cfg) == [ids[0], ids2[0]]
    assert helpers.get_jobs("c2d", ids2[1], lab.cfg, batch=True) == ids2
    assert helpers.get_jobs("c2d", ids2[1], lab.cfg) == [ids2[1]]


@pytest.fixture
def builds(lab, monkeypatch):
    """Fake config/build/install in lava: notes (step, flavor, jobs so far)."""
    from srt_build.commands import cmd_lava

    steps = []
    lab.fail = None

    def step(name):
        def run(ctx, *a):
            steps.append((name, ctx.args.flavor, len(lab.submitted)))
            return 1 if name == "build" and ctx.args.flavor == lab.fail else 0

        return run

    for name in ("config", "build", "install"):
        monkeypatch.setattr(cmd_lava, f"cmd_{name}", step(name))
    return steps


def test_build_first(lab, builds, capsys):
    """By default: every flavor once per board, all before the first job."""
    start(lab, skip_build=False)
    built = [f for s, f, _ in builds if s == "build"]
    assert built and sorted(built) == sorted(set(built))  # each once
    assert {n for _, _, n in builds} == {0}  # nothing submitted yet
    assert [s for s, _, _ in builds[:3]] == ["config", "build", "install"]
    assert lab.submitted and archive.round_ids(str(lab.top)) == ["1"]
    assert "c2d: built " in capsys.readouterr().out


def test_skip_build_builds_nothing(lab, builds):
    start(lab, skip_build=True)
    assert builds == [] and lab.submitted


def test_dry_run_does_not_build(lab, builds, capsys):
    start(lab, skip_build=False, dry_run=True)
    assert builds == [] and lab.submitted == []
    assert "builds first (not in a dry run)" in capsys.readouterr().out


def test_failed_build_submits_nothing(lab, builds):
    lab.fail = "rt"
    with pytest.raises(SystemExit, match="c2d rt: build failed"):
        start(lab, skip_build=False)
    assert ("install", "rt", 0) not in builds
    assert lab.submitted == [] and archive.round_ids(str(lab.top)) == []


def test_lavacli_that_does_not_run(monkeypatch, tmp_path, caplog):
    """A lavacli of a replaced Python: in PATH, but broken."""
    lavacli = tmp_path / "lavacli"
    lavacli.write_text(
        "#!/bin/sh\necho \"ModuleNotFoundError: No module named 'lavacli'\" >&2\n"
        "exit 1\n"
    )
    lavacli.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(SystemExit):
        helpers.ensure_lavacli_available()
    assert "does not run (ModuleNotFoundError" in caplog.text
    assert "pipx reinstall lavacli" in caplog.text


def test_header(lab, capsys):
    start(lab, dry_run=True, skip_build=False)
    out = capsys.readouterr().out
    assert (
        "  per board: build and install every flavor, then lava --skip-build; "
        "lava --skip-build --flavors rt --testsuites stress-ng-class" in out
    )
    start(lab, dry_run=True)
    assert "per board: the installed kernels, lava" in capsys.readouterr().out
    assert cmd_round_start.submission_command({"split": True}) == (
        "lava --skip-build --split"
    )


def test_repeat(lab, monkeypatch, capsys):
    """round repeat: N's jobs again, a new round, only srt.round differs."""
    imported(lab)
    for j in (1, 2, 3):
        lab.lava.jobs[j]["definition"] = yaml.safe_dump(
            {"job_name": f"job {j}", "metadata": {"srt.round": "12", "srt.board": "x"}}
        )
    rpc = FakeRpc(0)
    ids = iter([21, 22, 23])
    rpc.submit = lambda d: rpc.definitions.append(d) or [next(ids)]
    monkeypatch.setattr(cmd_round_start, "rpc_from_lavacli", lambda **kw: rpc)

    def repeat(**kw):
        args = {"round": "12", "test": False, "notes": None, "dry_run": False}
        args = SimpleNamespace(**{**args, "yes": False, **kw})
        cmd_round_start.cmd_round_repeat(args, lab.cfg, {})

    repeat(dry_run=True)
    assert "would submit again: 3" in capsys.readouterr().out
    assert rpc.definitions == []
    repeat()
    info = archive.load_round(str(lab.top), "13")
    assert info["repeats"] == "12" and info["notes"] == "repeat of 12"
    assert sorted(info["jobs"]) == [21, 22, 23]
    src = archive.load_round(str(lab.top), "12")
    assert info["jobs"][21] == src["jobs"][1]
    jobs = [yaml.safe_load(d) for d in rpc.definitions]
    assert [j["job_name"] for j in jobs] == ["job 1", "job 2", "job 3"]
    assert {j["metadata"]["srt.round"] for j in jobs} == {"13"}
    assert jobs[0]["metadata"]["srt.board"] == "x"
    # a test round, of the repeat
    for new, old in ((21, 1), (22, 2), (23, 3)):
        lab.lava.jobs[new] = dict(lab.lava.jobs[old], id=new)
    ids = iter([31, 32, 33])
    repeat(round="13", test=True)
    assert archive.load_round(str(lab.top), "t1")["repeats"] == "13"


def test_start_batch(lab, capsys):
    """--count 3: three rounds in one go, batch 1, priority low."""
    start(lab, dry_run=True, count=3)
    out = capsys.readouterr().out
    assert "3 rounds, one after another: 1, 2, 3 (batch 1)" in out
    assert "priority low" in out and "each of the 3 rounds:" in out
    assert lab.submitted == [] and archive.round_ids(str(lab.top)) == []
    start(lab, count=3, notes="baseline, back to back")
    assert archive.round_ids(str(lab.top)) == ["1", "2", "3"]
    assert archive.batch_rounds(str(lab.top), "1") == ["1", "2", "3"]
    per = len(lab.submitted) // 3
    for n, rid in enumerate(("1", "2", "3")):
        info = archive.load_round(str(lab.top), rid)
        assert info["batch"] == "1" and info["priority"] == "low"
        assert info["notes"] == "baseline, back to back"
        jobs = lab.submitted[n * per : (n + 1) * per]
        assert {j["metadata"]["srt.round"] for j in jobs} == {rid}
        assert {j["priority"] for j in jobs} == {"low"}
        assert len(info["jobs"]) == per
    # One round: medium, no batch, as before; --priority as given.
    start(lab)
    info = archive.load_round(str(lab.top), "4")
    assert "batch" not in info and "priority" not in info
    assert lab.submitted[-1]["priority"] == "medium"
    start(lab, priority="high")
    assert archive.load_round(str(lab.top), "5")["priority"] == "high"
    assert lab.submitted[-1]["priority"] == "high"


def test_start_batch_refuses(lab):
    with pytest.raises(SystemExit, match="not --round"):
        start(lab, count=2, round="7")
    with pytest.raises(SystemExit, match="1 or more"):
        start(lab, count=0)
    with pytest.raises(SystemExit, match="bad priority"):
        start(lab, priority="urgent")
    with pytest.raises(SystemExit, match="bad priority"):
        start(lab, priority="101")
    assert cmd_round_start.parse_priority("40") == 40
    assert lab.submitted == []


def test_start_batch_builds_once(lab, builds):
    start(lab, skip_build=False, count=2)
    built = [f for s, f, _ in builds if s == "build"]
    assert sorted(built) == sorted(set(built))
    assert archive.round_ids(str(lab.top)) == ["1", "2"]


def test_disk_scales_with_count(lab, monkeypatch):
    monkeypatch.setattr(cmd_round_start, "lava_free_gb", lambda c: 12)
    assert cmd_round_start.disk_warnings(lab.cfg) == []
    assert cmd_round_start.disk_warnings(lab.cfg, 3) == []  # 10 + 2 x 1
    (w,) = cmd_round_start.disk_warnings(lab.cfg, 4)
    assert w == ("the LAVA server has 12G free, less than the 13G 4 rounds "
                 "need (10G and 1G per round after the first)")  # fmt: skip
    cfg = {**lab.cfg, "lava-round-gb": 2}
    assert cmd_round_start.disk_warnings(cfg, 2) == []
    assert cmd_round_start.disk_warnings(cfg, 3)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("n\n"))
    with pytest.raises(SystemExit, match="nothing submitted"):
        start(lab, count=4)
    assert lab.submitted == []


def test_repeat_batch(lab, monkeypatch, capsys):
    """round repeat 12 --count 3: rounds 13-15 of batch 13, jobs low."""
    imported(lab)
    for j in (1, 2, 3):
        lab.lava.jobs[j]["definition"] = yaml.safe_dump(
            {"job_name": f"job {j}", "priority": "medium",
             "metadata": {"srt.round": "12"}}  # fmt: skip
        )
    rpc = FakeRpc(0)
    ids = iter(range(21, 40))
    rpc.submit = lambda d: rpc.definitions.append(d) or [next(ids)]
    monkeypatch.setattr(cmd_round_start, "rpc_from_lavacli", lambda **kw: rpc)

    def repeat(**kw):
        args = {"round": "12", "test": False, "notes": None, "dry_run": False}
        args = SimpleNamespace(**{**args, "yes": False, **kw})
        cmd_round_start.cmd_round_repeat(args, lab.cfg, {})

    repeat(dry_run=True, count=3)
    out = capsys.readouterr().out
    assert "3 rounds, one after another: 13, 14, 15 (batch 13)" in out
    assert rpc.definitions == []
    repeat(count=3)
    assert archive.batch_rounds(str(lab.top), "13") == ["13", "14", "15"]
    jobs = [yaml.safe_load(d) for d in rpc.definitions]
    assert [j["metadata"]["srt.round"] for j in jobs] == ["13"] * 3 + ["14"] * 3 + [
        "15"
    ] * 3
    assert {j["priority"] for j in jobs} == {"low"}
    for rid, first in (("13", 21), ("14", 24), ("15", 27)):
        info = archive.load_round(str(lab.top), rid)
        assert info["batch"] == "13" and info["repeats"] == "12"
        assert info["priority"] == "low"
        assert sorted(info["jobs"]) == [first, first + 1, first + 2]
    # One repeat keeps the definition's priority unless --priority.
    rpc.definitions.clear()
    repeat()
    assert yaml.safe_load(rpc.definitions[0])["priority"] == "medium"
    assert "batch" not in archive.load_round(str(lab.top), "16")
    rpc.definitions.clear()
    repeat(priority="30")
    assert yaml.safe_load(rpc.definitions[0])["priority"] == 30


def test_repeat_some(lab, monkeypatch, capsys):
    """round repeat --boards/--tests: only those jobs of N, notes say so."""
    imported(lab)
    src = archive.load_round(str(lab.top), "12")
    assert cmd_round_start.selected_jobs(src) == [1, 2, 3]
    assert cmd_round_start.selected_jobs(src, "bbb", "cyclictest") == [1, 2]
    with pytest.raises(SystemExit, match="no board rpi3-32 .it has: bbb, c2d"):
        cmd_round_start.selected_jobs(src, "bbb,rpi3-32")
    with pytest.raises(SystemExit, match="no test stress-ng-io"):
        cmd_round_start.selected_jobs(src, tests="stress-ng-io")
    rpc = FakeRpc(0)
    ids = iter(range(21, 40))
    rpc.submit = lambda d: rpc.definitions.append(d) or [next(ids)]
    monkeypatch.setattr(cmd_round_start, "rpc_from_lavacli", lambda **kw: rpc)
    args = SimpleNamespace(
        round="12", test=True, notes=None, dry_run=False, yes=False,
        boards="c2d", tests="cyclictest", count=2,
    )  # fmt: skip
    cmd_round_start.cmd_round_repeat(args, lab.cfg, {})
    assert "1 jobs" in capsys.readouterr().out
    for rid, job in (("t1", 21), ("t2", 22)):
        info = archive.load_round(str(lab.top), rid)
        assert list(info["jobs"]) == [job] and info["boards"] == ["c2d"]
        assert info["notes"] == "repeat of 12 (cyclictest, c2d)"
