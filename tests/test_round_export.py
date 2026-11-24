"""round export: the samples of `jobs export`, from the archive, with
the round label."""

import json
from types import SimpleNamespace

import pytest

import lava_fake
from srt_build import archive, victoria
from srt_build.commands import cmd_jobs_export, cmd_round_export, cmd_round_report


@pytest.fixture
def lab(tmp_path, monkeypatch, deleted):
    jobs = [lava_fake.job(1, "bbb"), lava_fake.job(2, "c2d"), lava_fake.job(3, "c2d")]
    lava = lava_fake.FakeLava(jobs, latencies={2: 77})
    monkeypatch.setattr(
        cmd_round_report.LavaApi, "from_config", classmethod(lambda c, s: lava)
    )
    monkeypatch.setattr(archive, "fetch_url", lava_fake.upload)
    cfg = tmp_path / "metrics.yml"
    cfg.write_text("url: http://vm.test:8427\n")
    system_config = {
        "round-archive": str(tmp_path / "rounds"),
        "lava-instance": "lava.test",
        "artifactorial-token": "FAKE-UPLOAD-TOKEN",
        "metrics-config": str(cfg),
    }
    cmd_round_report.cmd_round_import(
        SimpleNamespace(round=12, ids="1-3", no_export=True), system_config, {}
    )
    return SimpleNamespace(lava=lava, cfg=system_config)


def args(**kw):
    return SimpleNamespace(**{"round": None, "all": False, "dry_run": False,
                              "force": False, **kw})  # fmt: skip


def lines(text):
    return [json.loads(x) for x in text.splitlines()]


def test_same_samples_as_jobs_export(lab, monkeypatch, capsys):
    """Per sample: the round label is the only difference."""
    monkeypatch.setattr(
        cmd_jobs_export,
        "fetch_artifacts",
        lambda urls: {n: json.loads(lava_fake.upload(u)) for n, u in urls.items()},
    )
    capsys.readouterr()
    cmd_round_export.cmd_round_export(args(dry_run=True), lab.cfg, {})
    from_archive = lines(capsys.readouterr().out)
    from_lava = []
    for jid in (1, 2, 3):
        from_lava += cmd_jobs_export.collect(lab.lava, lab.lava.job(jid))
    assert len(from_archive) == len(from_lava) > 30
    for a, b in zip(from_archive, from_lava):
        assert a["metric"].pop("round") == "12"
        assert a["metric"].pop("round_kind") == "release"
        assert a == b
    assert any(s["metric"]["__name__"] == "srt_latency_bucket" for s in from_lava)


def test_replaced_jobs_left_out(lab, capsys):
    info = archive.load_round(lab.cfg["round-archive"], "12")
    info["reruns"] = {2: 3}
    archive.save_round(lab.cfg["round-archive"], info)
    capsys.readouterr()
    cmd_round_export.cmd_round_export(args(dry_run=True), lab.cfg, {})
    assert {s["metric"]["job"] for s in lines(capsys.readouterr().out)} == {"1", "3"}


def test_send_once(lab, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(victoria, "send", lambda cfg, body: sent.append(body))
    cmd_round_export.cmd_round_export(args(round="12"), lab.cfg, {})
    assert len(sent) == 3
    assert archive.load_round(lab.cfg["round-archive"], "12")["exported"]
    cmd_round_export.cmd_round_export(args(round="12"), lab.cfg, {})
    assert len(sent) == 3
    assert "--force sends it again" in capsys.readouterr().out
    cmd_round_export.cmd_round_export(args(all=True), lab.cfg, {})
    cmd_round_export.cmd_round_export(args(), lab.cfg, {})
    assert len(sent) == 3
    assert "every round went out" in capsys.readouterr().err
    cmd_round_export.cmd_round_export(args(all=True, force=True), lab.cfg, {})
    assert len(sent) == 6


def report(lab, **kw):
    a = SimpleNamespace(**{"round": "12", "keep_uploads": False, "no_export": False,
                           "json": False, **kw})  # fmt: skip
    cmd_round_report.cmd_round_report(a, lab.cfg, {})


def test_report_exports_once(lab, monkeypatch, capsys):
    """round report sends a whole round that hasn't gone out, once."""
    sent = []
    monkeypatch.setattr(victoria, "send", lambda cfg, body: sent.append(body))
    report(lab)
    assert len(sent) == 3
    assert archive.load_round(lab.cfg["round-archive"], "12")["exported"]
    assert "round 12: sent " in capsys.readouterr().err
    report(lab)
    assert len(sent) == 3


@pytest.mark.parametrize("flag", ["no_export", "keep_uploads"])
def test_report_without_export(lab, monkeypatch, flag):
    """--no-export, and --keep-uploads (a second archive): nothing sent."""
    sent = []
    monkeypatch.setattr(victoria, "send", lambda cfg, body: sent.append(body))
    report(lab, **{flag: True})
    assert sent == []
    assert not archive.load_round(lab.cfg["round-archive"], "12").get("exported")


def test_report_export_fails(lab, monkeypatch, capsys):
    """VictoriaMetrics away: the report stands, round export later."""
    def away(cfg, body):
        raise OSError("connection refused")

    monkeypatch.setattr(victoria, "send", away)
    report(lab)
    err = capsys.readouterr().err
    assert "round 12: not exported (job 1: sending failed: connection refused)" in err
    assert "round export 12 sends it" in err
    assert not archive.load_round(lab.cfg["round-archive"], "12").get("exported")
