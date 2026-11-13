"""round import, report and list on a fake LAVA."""

import gzip
import os
from types import SimpleNamespace

import pytest

import lava_fake
from srt_build import archive
from srt_build.commands import cmd_round, cmd_round_report


@pytest.fixture
def lab(tmp_path, monkeypatch, deleted):
    """A fake LAVA with round 12's jobs 1-3 (3 still running) and a
    system_config with the archive in tmp_path."""
    lava = lava_fake.FakeLava(
        [
            lava_fake.job(1, "bbb"),
            lava_fake.job(2, "c2d", health="Incomplete"),
            lava_fake.job(3, "c2d", "rt-isolcpus", state="Running"),
        ]
    )
    monkeypatch.setattr(
        cmd_round_report.LavaApi, "from_config", classmethod(lambda c, s: lava)
    )
    monkeypatch.setattr(archive, "fetch_url", lava_fake.upload)
    cfg = {
        "round-archive": str(tmp_path / "rounds"),
        "lava-instance": "lava.test",
        "artifactorial-token": "FAKE-UPLOAD-TOKEN",
    }
    return SimpleNamespace(lava=lava, cfg=cfg, archive=tmp_path / "rounds")


def run_import(lab, ids="1-3"):
    args = SimpleNamespace(round=12, ids=ids)
    with pytest.raises(SystemExit) as e:  # job 2 is Incomplete: a problem
        cmd_round_report.cmd_round_import(args, lab.cfg, {})
    assert e.value.code == 1


def test_import_then_report(lab, capsys):
    run_import(lab)
    info = archive.load_round(str(lab.archive), 12)
    assert sorted(info["jobs"]) == [1, 2, 3]
    assert info["jobs"][3] == {"board": "c2d", "flavor": "rt-isolcpus",
                               "test": "cyclictest"}  # fmt: skip
    assert info["lava"] == "lava.test"
    assert info["test_definitions"]["commit"] == "f6a8ad13"
    assert "reported" not in info  # job 3 is running
    rdir = archive.round_dir(str(lab.archive), 12)
    assert archive.is_complete(rdir, 1) and not archive.is_complete(rdir, 3)
    out = capsys.readouterr().out
    assert "3 jobs, 1 Complete, 1 Incomplete, 1 not finished" in out
    assert (lab.archive / "12" / "report.txt").read_text().strip() == out.strip()

    # Job 3 finishes: the next report fetches it, and only it.
    lab.lava.jobs[3]["state"] = "Finished"
    lab.lava.jobs[3]["health"] = "Complete"
    lab.lava.asked.clear()
    with pytest.raises(SystemExit):
        cmd_round_report.cmd_round_report(SimpleNamespace(round=None), lab.cfg, {})
    assert {jid for _, jid in lab.lava.asked} == {3}
    info = archive.load_round(str(lab.archive), 12)
    assert info["reported"]
    assert "3 jobs, 2 Complete, 1 Incomplete" in capsys.readouterr().out


def test_report_from_the_archive_alone(lab, monkeypatch, capsys):
    lab.lava.jobs[3]["state"] = "Finished"
    run_import(lab)
    capsys.readouterr()

    def no_lava(*a):
        raise AssertionError("LAVA asked")

    monkeypatch.setattr(cmd_round_report.LavaApi, "from_config", no_lava)
    with pytest.raises(SystemExit):
        cmd_round_report.cmd_round_report(SimpleNamespace(round=12), lab.cfg, {})
    assert "problems in jobs 2" in capsys.readouterr().out


def test_no_archived_file_has_a_secret(lab):
    run_import(lab)
    n = 0
    for root, _, files in os.walk(lab.archive):
        for name in files:
            with open(os.path.join(root, name), "rb") as f:
                data = f.read()
            if name.endswith(".gz"):
                data = gzip.decompress(data)
            assert lava_fake.TOKEN.encode() not in data, name
            assert lava_fake.JOB_TOKEN.encode() not in data, name
            n += 1
    assert n > 10


def test_import_adds_to_a_round(lab):
    lab.lava.jobs[2]["health"] = "Complete"
    cmd_round_report.cmd_round_import(SimpleNamespace(round=12, ids="1"), lab.cfg, {})
    cmd_round_report.cmd_round_import(SimpleNamespace(round=12, ids="2"), lab.cfg, {})
    assert sorted(archive.load_round(str(lab.archive), 12)["jobs"]) == [1, 2]


def test_other_lava_instance_refused(lab):
    run_import(lab)
    lab.cfg["lava-instance"] = "lava.elsewhere"
    with pytest.raises(SystemExit, match="ran on lava.test"):
        cmd_round_report.cmd_round_report(SimpleNamespace(round=12), lab.cfg, {})


def test_list(lab, capsys):
    run_import(lab)
    capsys.readouterr()
    cmd_round.cmd_round_list(SimpleNamespace(test=True), lab.cfg, {})
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:3] == ["round", "started", "kernel"]
    assert lines[1].split()[:6] == [
        "12",
        "2026-11-13",
        "v6.12.117-rt23",
        "9e82b80d6821",
        "3",
        "2",
    ]
    assert lines[1].endswith("problems in jobs 2")


def test_a_job_is_in_one_round(lab):
    run_import(lab)
    args = SimpleNamespace(round=13, ids="2-3")
    with pytest.raises(SystemExit, match="already in a round.*2 \\(round 12\\)"):
        cmd_round_report.cmd_round_import(args, lab.cfg, {})
    assert "13" not in archive.round_ids(str(lab.archive))


def test_import_a_test_round(lab):
    lab.lava.jobs[2]["health"] = "Complete"
    args = SimpleNamespace(round="4", ids="1-2", test=True, notes="nohz=off try")
    cmd_round_report.cmd_round_import(args, lab.cfg, {})
    info = archive.load_round(str(lab.archive), "t4")
    assert info["kind"] == "test" and info["notes"] == "nohz=off try"
    assert (lab.archive / "test" / "t4" / "report.txt").exists()
    # Job ids are unique over both kinds.
    with pytest.raises(SystemExit, match="1 \\(round t4\\)"):
        cmd_round_report.cmd_round_import(
            SimpleNamespace(round="12", ids="1"), lab.cfg, {}
        )


def test_report_deletes_archived_uploads(lab, deleted):
    lab.lava.jobs[3]["state"] = "Finished"
    run_import(lab)
    assert sorted(deleted) == [
        f"http://artifactorial.invalid/artifacts/rt-tests/{j}/cyclictest.json"
        for j in (1, 2, 3)
    ]
    with pytest.raises(SystemExit):
        cmd_round_report.cmd_round_report(SimpleNamespace(round="12"), lab.cfg, {})
    assert len(deleted) == 3  # not again


def test_keep_uploads(lab, deleted):
    args = SimpleNamespace(round="12", ids="1-3", keep_uploads=True)
    with pytest.raises(SystemExit):
        cmd_round_report.cmd_round_import(args, lab.cfg, {})
    assert deleted == []
