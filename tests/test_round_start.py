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
    args = SimpleNamespace(**{**args, "dry_run": False, "yes": False, **kw})
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
