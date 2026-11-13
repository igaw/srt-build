"""round status, wait and compare, on a fake LAVA."""

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
