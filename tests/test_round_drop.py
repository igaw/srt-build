"""round drop, round prune and jobs purge remove everything, after
asking; tested on fakes only (no real Artifactorial or VictoriaMetrics)."""

import io
from types import SimpleNamespace

import pytest

import lava_fake
from srt_build import archive, config, victoria
from srt_build.commands import (
    cmd_jobs_purge,
    cmd_round_drop,
    cmd_round_report,
)


@pytest.fixture
def lab(tmp_path, monkeypatch, deleted):
    lava = lava_fake.FakeLava([lava_fake.job(j) for j in range(1, 8)])
    for cls in (cmd_round_report.LavaApi, cmd_jobs_purge.LavaApi):
        monkeypatch.setattr(cls, "from_config", classmethod(lambda c, s: lava))
    monkeypatch.setattr(archive, "fetch_url", lava_fake.upload)
    series = []
    monkeypatch.setattr(cmd_round_drop, "delete_series", lambda c, m: series.append(m))
    monkeypatch.setattr(cmd_jobs_purge, "delete_series", lambda c, m: series.append(m))
    metrics = tmp_path / "metrics.yml"
    metrics.write_text("url: http://vm.invalid:8427\n")
    cfg = {
        "round-archive": str(tmp_path / "rounds"),
        "lava-instance": "lava.test",
        "artifactorial-token": "FAKE-UPLOAD-TOKEN",
        "metrics-config": str(metrics),
    }
    for rid, ids, test in (("12", "1-2", False), ("3", "3", True)):
        args = SimpleNamespace(round=rid, ids=ids, test=test, keep_uploads=True)
        cmd_round_report.cmd_round_import(args, cfg, {})
    return SimpleNamespace(cfg=cfg, top=tmp_path / "rounds", series=series,
                           deleted=deleted)  # fmt: skip


def opts(**kw):
    return SimpleNamespace(**{"metrics": False, "dry_run": False, "yes": False, **kw})


def test_dry_run_deletes_nothing(lab, capsys):
    cmd_round_drop.cmd_round_drop(opts(round="12", dry_run=True, metrics=True),
                                  lab.cfg, {})  # fmt: skip
    out = capsys.readouterr().out
    assert "2 uploads on Artifactorial" in out
    assert 'series {round="12", round_kind="release"}' in out
    assert (lab.top / "12").exists() and not lab.deleted and not lab.series


def test_drop_asks(lab, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    with pytest.raises(SystemExit, match="nothing removed"):
        cmd_round_drop.cmd_round_drop(opts(round="12"), lab.cfg, {})
    assert (lab.top / "12").exists()


def test_drop_removes_everything(lab):
    cmd_round_drop.cmd_round_drop(opts(round="12", yes=True, metrics=True),
                                  lab.cfg, {})  # fmt: skip
    assert not (lab.top / "12").exists()
    assert archive.round_ids(str(lab.top)) == ["t3"]
    from srt_build.rounds import jobs_in_rounds

    assert jobs_in_rounds(str(lab.top), "lava.test", [1, 2]) == {}
    assert sorted(lab.deleted) == [
        f"http://artifactorial.invalid/artifacts/rt-tests/{j}/cyclictest.json"
        for j in (1, 2)
    ]
    assert lab.series == ['{round="12", round_kind="release"}']


def test_prune_only_expired_test_rounds(lab, monkeypatch, capsys):
    monkeypatch.setattr(config, "rounds", {"test-retention-days": 30})
    cmd_round_drop.cmd_round_prune(opts(yes=True), lab.cfg, {})
    assert "no test round older than 30 days" in capsys.readouterr().out
    info = archive.load_round(str(lab.top), "t3")
    info["started"] = "2026-01-01T00:00:00Z"
    archive.save_round(str(lab.top), info)
    old = archive.load_round(str(lab.top), "12")
    old["started"] = "2025-01-01T00:00:00Z"  # release rounds never expire
    archive.save_round(str(lab.top), old)
    cmd_round_drop.cmd_round_prune(opts(yes=True, metrics=True), lab.cfg, {})
    assert archive.round_ids(str(lab.top)) == ["12"]
    assert lab.series == ['{round="t3", round_kind="test"}']


def test_purge_refuses_round_jobs(lab):
    with pytest.raises(SystemExit, match="use round drop: 2 \\(round 12\\)"):
        cmd_jobs_purge.cmd_jobs_purge(opts(ids="2,5"), lab.cfg, {})
    assert not lab.deleted


def test_purge(lab, capsys):
    cmd_jobs_purge.cmd_jobs_purge(opts(ids="5-6", dry_run=True, metrics=True),
                                  lab.cfg, {})  # fmt: skip
    assert 'job 5: 1 uploads on Artifactorial, VictoriaMetrics series {job="5"}' in (
        capsys.readouterr().out
    )
    assert not lab.deleted
    cmd_jobs_purge.cmd_jobs_purge(opts(ids="5-6", yes=True, metrics=True),
                                  lab.cfg, {})  # fmt: skip
    assert len(lab.deleted) == 2
    assert lab.series == ['{job="5"}', '{job="6"}']


def test_delete_series_request():
    seen = []

    def opener(req, timeout=None):
        seen.append(req)
        return io.BytesIO(b"")

    cfg = {"url": "http://vm.invalid:8427/", "username": "u", "password": "p"}
    victoria.delete_series(cfg, '{round="t3"}', opener=opener)
    (req,) = seen
    assert req.full_url == "http://vm.invalid:8427/api/v1/admin/tsdb/delete_series"
    assert req.data == b"match%5B%5D=%7Bround%3D%22t3%22%7D"
    assert req.get_header("Authorization").startswith("Basic ")
