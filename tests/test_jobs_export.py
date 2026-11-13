"""jobs export: exactly the jobs asked for, with their round's labels
if the archive knows them; without arguments the newest round not
exported yet. Nothing is tracked per job."""

import json
from types import SimpleNamespace

import pytest

import lava_fake
from srt_build import archive, victoria
from srt_build.commands import cmd_jobs_export as ex
from srt_build.commands import cmd_round_report


@pytest.fixture
def lab(tmp_path, monkeypatch, deleted):
    lava = lava_fake.FakeLava(
        [lava_fake.job(1), lava_fake.job(2), lava_fake.job(3, state="Running")]
    )
    for mod in (ex, cmd_round_report):
        monkeypatch.setattr(mod.LavaApi, "from_config", classmethod(lambda c, s: lava))
    monkeypatch.setattr(archive, "fetch_url", lava_fake.upload)
    monkeypatch.setattr(
        ex,
        "fetch_artifacts",
        lambda urls: {n: json.loads(lava_fake.upload(u)) for n, u in urls.items()},
    )
    sent = []
    monkeypatch.setattr(victoria, "send", lambda cfg, body: sent.append(body))
    metrics = tmp_path / "metrics.yml"
    metrics.write_text("url: http://vm.invalid:8427\n")
    cfg = {
        "round-archive": str(tmp_path / "rounds"),
        "lava-instance": "lava.test",
        "artifactorial-token": "FAKE-UPLOAD-TOKEN",
        "metrics-config": str(metrics),
    }
    return SimpleNamespace(lava=lava, cfg=cfg, sent=sent)


def args(**kw):
    a = {"machines": [], "since": None, "ids": None, "health_checks": False}
    return SimpleNamespace(**{**a, "dry_run": False, "no_artifacts": False, **kw})


def jobs_sent(lab):
    return [
        {json.loads(line)["metric"]["job"] for line in body.splitlines()}
        for body in lab.sent
    ]


def test_ids_exactly_and_every_time(lab):
    ex.cmd_jobs_export(args(ids="1-3"), lab.cfg, {})
    assert jobs_sent(lab) == [{"1"}, {"2"}]  # 3 is still running
    ex.cmd_jobs_export(args(ids="1"), lab.cfg, {})
    assert jobs_sent(lab)[-1] == {"1"}  # nothing remembered: again
    assert '"round"' not in lab.sent[0]


def test_round_labels_from_the_archive(lab):
    cmd_round_report.cmd_round_import(SimpleNamespace(round="12", ids="1"), lab.cfg, {})
    ex.cmd_jobs_export(args(ids="1-2"), lab.cfg, {})
    first = json.loads(lab.sent[0].splitlines()[0])["metric"]
    assert first["round"] == "12" and first["round_kind"] == "release"
    assert '"round"' not in lab.sent[1]


def test_no_arguments_newest_round_not_exported(lab, capsys):
    ex.cmd_jobs_export(args(), lab.cfg, {})
    assert "every round went out" in capsys.readouterr().err
    cmd_round_report.cmd_round_import(SimpleNamespace(round="12", ids="1"), lab.cfg, {})
    cmd_round_report.cmd_round_import(SimpleNamespace(round="13", ids="2"), lab.cfg, {})
    ex.cmd_jobs_export(args(), lab.cfg, {})
    assert jobs_sent(lab) == [{"2"}]
    assert archive.load_round(lab.cfg["round-archive"], "13")["exported"]
    ex.cmd_jobs_export(args(), lab.cfg, {})
    assert jobs_sent(lab) == [{"2"}, {"1"}]
    ex.cmd_jobs_export(args(), lab.cfg, {})
    assert len(lab.sent) == 2
