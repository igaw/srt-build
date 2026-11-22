"""round status, wait and compare, on a fake LAVA."""

import json
from types import SimpleNamespace

import pytest

import lava_fake
from srt_build import archive
from srt_build.commands import cmd_round_compare, cmd_round_report, cmd_round_status


@pytest.fixture
def lab(tmp_path, monkeypatch, deleted):
    lava = lava_fake.FakeLava([])
    for mod in (cmd_round_report, cmd_round_status):
        monkeypatch.setattr(mod.LavaApi, "from_config", classmethod(lambda c, s: lava))
    monkeypatch.setattr(cmd_round_status, "lava_free_gb", lambda c: 30)
    monkeypatch.setattr(archive, "fetch_url", lava_fake.upload)
    cfg = {
        "round-archive": str(tmp_path / "rounds"),
        "lava-instance": "lava.test",
        "artifactorial-token": "FAKE-UPLOAD-TOKEN",
    }
    return SimpleNamespace(cfg=cfg, top=tmp_path / "rounds", lava=lava)


def imported(lab, ids=(1, 2, 3)):
    for j in ids:
        lab.lava.jobs[j] = lava_fake.job(j, "bbb" if j < 3 else "c2d", round="12")
    args = SimpleNamespace(round="12", ids=",".join(map(str, ids)))
    cmd_round_report.cmd_round_import(args, lab.cfg, {})


def test_status_and_wait(lab, monkeypatch, capsys):
    imported(lab)
    lab.lava.jobs[5] = lava_fake.job(5, "c2d", state="Running")
    info = archive.load_round(str(lab.top), "12")
    info["jobs"][5] = {"board": "c2d", "flavor": "rt", "test": "cyclictest"}
    info["reruns"] = {3: 5}
    archive.save_round(str(lab.top), info)
    capsys.readouterr()
    cmd_round_status.cmd_round_status(SimpleNamespace(round=None), lab.cfg, {})
    out = capsys.readouterr().out
    assert "replaced by 5" in out and "rerun of 3" in out
    assert "round 12: 2 Complete, 1 Running; LAVA disk free: 30G" in out

    def finish(seconds):  # the job ends while wait sleeps
        lab.lava.jobs[5].update(state="Finished", health="Incomplete")

    with pytest.raises(SystemExit):
        cmd_round_status.cmd_round_wait(
            SimpleNamespace(round="12", interval=1), lab.cfg, {}, sleep=finish
        )
    out = capsys.readouterr().out
    assert "job 5 c2d rt cyclictest: Incomplete" in out
    assert "round 12: 3 jobs finished, 1 not Complete" in out


def test_compare(lab, capsys):
    imported(lab, (1, 3))
    lab.lava.jobs[7] = lava_fake.job(7, "bbb")
    lab.lava.jobs[8] = lava_fake.job(8, "c2d", health="Incomplete")
    lab.lava.latencies.update({7: 63, 8: 21})
    with pytest.raises(SystemExit):
        cmd_round_report.cmd_round_import(
            SimpleNamespace(round="2", ids="7-8", test=True), lab.cfg, {}
        )
    capsys.readouterr()
    cmd_round_compare.cmd_round_compare(SimpleNamespace(a="12", b="t2"), lab.cfg, {})
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["board", "flavor", "test", "workload", "12", "t2",
                                "change"]  # fmt: skip
    assert lines[1].split() == ["bbb", "rt", "cyclictest", "hackbench", "42", "63",
                                "+50%"]  # fmt: skip
    assert lines[2].split() == ["c2d", "rt", "cyclictest", "hackbench", "42", "21",
                                "-50%"]  # fmt: skip
    assert "problems in round t2:" in lines


def test_status_json(lab, capsys):
    imported(lab)
    lab.lava.jobs[5] = lava_fake.job(5, "c2d", state="Running")
    info = archive.load_round(str(lab.top), "12")
    info["jobs"][5] = {"board": "c2d", "flavor": "rt", "test": "cyclictest"}
    info["reruns"] = {3: 5}
    archive.save_round(str(lab.top), info)
    capsys.readouterr()
    cmd_round_status.cmd_round_status(
        SimpleNamespace(round=None, json=True), lab.cfg, {}
    )
    out = json.loads(capsys.readouterr().out)
    assert out["round"] == "12"
    assert out["counts"] == {"Complete": 2, "Running": 1}
    assert out["finished"] is False
    assert out["lava_disk_free_gb"] == 30
    jobs = {j["id"]: j for j in out["jobs"]}
    assert jobs[3]["replaced_by"] == 5 and jobs[5]["rerun_of"] == 3
    assert jobs[5]["state"] == "Running"


def test_compare_json(lab, capsys):
    imported(lab, (1, 3))
    lab.lava.jobs[7] = lava_fake.job(7, "bbb")
    lab.lava.jobs[8] = lava_fake.job(8, "c2d", health="Incomplete")
    lab.lava.latencies.update({7: 63, 8: 21})
    with pytest.raises(SystemExit):
        cmd_round_report.cmd_round_import(
            SimpleNamespace(round="2", ids="7-8", test=True), lab.cfg, {}
        )
    capsys.readouterr()
    cmd_round_compare.cmd_round_compare(
        SimpleNamespace(a="12", b="t2", json=True), lab.cfg, {}
    )
    out = json.loads(capsys.readouterr().out)
    assert out["rows"][0] == {
        "board": "bbb",
        "flavor": "rt",
        "test": "cyclictest",
        "workload": "hackbench",
        "a": 42,
        "b": 63,
        "change_percent": 50.0,
    }
    assert out["problems"]["t2"]


def test_wait_survives_lava_away(lab, monkeypatch, capsys):
    """A proxy error while waiting: wait goes on, it doesn't end."""
    import urllib.error

    imported(lab)
    lab.lava.jobs[5] = lava_fake.job(5, "c2d", state="Running")
    info = archive.load_round(str(lab.top), "12")
    info["jobs"][5] = {"board": "c2d", "flavor": "rt", "test": "cyclictest"}
    archive.save_round(str(lab.top), info)
    real = cmd_round_status.job_states
    calls = []

    def flaky(*a):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("u", 502, "Proxy Error", {}, None)
        return real(*a)

    monkeypatch.setattr(cmd_round_status, "job_states", flaky)

    def finish(seconds):
        if len(calls) > 1:
            lab.lava.jobs[5].update(state="Finished", health="Complete")

    cmd_round_status.cmd_round_wait(
        SimpleNamespace(round="12", interval=1), lab.cfg, {}, sleep=finish
    )
    assert "warning: LAVA: HTTP Error 502" in capsys.readouterr().err
    assert len(calls) == 3


def test_api_retries_proxy_errors(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    from srt_build.lava_api import LavaApi

    answers = [
        urllib.error.HTTPError("u", 502, "Proxy Error", {}, None),
        urllib.error.URLError("refused"),
        io.BytesIO(b'{"id": 7}'),
    ]

    def urlopen(req, timeout):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    api = LavaApi("http://lava.test/api/v0.2/")
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    assert api.job(7) == {"id": 7}
    assert slept == [5, 15]
    # a 404 is an answer, not LAVA away
    answers[:] = [urllib.error.HTTPError("u", 404, "Not Found", {}, None)]
    with pytest.raises(urllib.error.HTTPError):
        api.job(8)


def batch(lab):
    """Rounds 12 (jobs 1-3, finished) and 13 (jobs 4-5, running), a batch."""
    imported(lab)
    for j in (4, 5):
        lab.lava.jobs[j] = lava_fake.job(j, "c2d", state="Running", round="13")
    cmd_round_report.cmd_round_import(SimpleNamespace(round="13", ids="4,5"),
                                      lab.cfg, {})  # fmt: skip
    for rid in ("12", "13"):
        info = archive.load_round(str(lab.top), rid)
        info["batch"] = "12"
        archive.save_round(str(lab.top), info)


def test_wait_batch_report(lab, capsys):
    """round wait --batch 12 --report: each round, reported when done."""
    batch(lab)
    capsys.readouterr()
    order = []

    def finish(seconds):  # round 12 is reported before 13 finishes
        order.append(archive.load_round(str(lab.top), "12").get("reported"))
        for j in (4, 5):
            lab.lava.jobs[j].update(state="Finished", health="Complete")

    args = SimpleNamespace(round=None, batch="12", interval=1, report=True,
                           keep_uploads=True)  # fmt: skip
    cmd_round_status.cmd_round_wait(args, lab.cfg, {}, sleep=finish)
    out = capsys.readouterr().out
    assert out.index("round 12: 3 jobs finished") < out.index("round 13: 2 jobs")
    assert order and order[0]  # 12 was reported while 13 still ran
    for rid in ("12", "13"):
        assert archive.load_round(str(lab.top), rid).get("reported")
    with pytest.raises(SystemExit, match="not both"):
        cmd_round_status.cmd_round_wait(
            SimpleNamespace(round="12", batch="12", interval=1), lab.cfg, {}
        )
    with pytest.raises(SystemExit, match="no rounds of batch 7"):
        cmd_round_status.cmd_round_wait(
            SimpleNamespace(round=None, batch="7", interval=1), lab.cfg, {}
        )


def test_cancel(lab, monkeypatch, capsys):
    batch(lab)
    canceled = []
    rpc = SimpleNamespace(scheduler=SimpleNamespace(
        jobs=SimpleNamespace(cancel=canceled.append)))  # fmt: skip
    monkeypatch.setattr(cmd_round_status, "rpc_from_lavacli", lambda **kw: rpc)

    def cancel(**kw):
        args = {"round": None, "batch": None, "dry_run": False, "yes": False}
        cmd_round_status.cmd_round_cancel(SimpleNamespace(**{**args, **kw}),
                                          lab.cfg, {})  # fmt: skip

    capsys.readouterr()
    cancel(batch="12", dry_run=True)
    out = capsys.readouterr().out
    assert "13  4  c2d" in out and "13  5  c2d" in out and "12  1" not in out
    assert canceled == []
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("n\n"))
    with pytest.raises(SystemExit, match="nothing canceled"):
        cancel(round="13")
    cancel(batch="12", yes=True)
    assert canceled == [4, 5]
    assert "2 jobs canceled; the rounds stay in the archive" in (
        capsys.readouterr().out
    )
    cancel(round="12")
    assert "no job left to cancel" in capsys.readouterr().out
    assert archive.round_ids(str(lab.top)) == ["12", "13"]
