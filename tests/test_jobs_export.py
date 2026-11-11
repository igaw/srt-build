"""jobs export sends each finished job once."""

from types import SimpleNamespace

from srt_build.commands import cmd_jobs_export as ex


class FakeApi:
    def tests(self, job_id):
        return [
            {
                "name": "t0-max-latency",
                "result": "pass",
                "measurement": "42",
                "suite": "1_cyclictest",
            }
        ]

    def suites(self, job_id):
        return []

    def log(self, job_id):
        return ""


JOBS = [
    {
        "id": 1,
        "state": "Finished",
        "health": "Complete",
        "description": "cyclictest",
        "actual_device": "bbb",
        "end_time": "2026-11-11T10:00:00Z",
        "definition": "",
    },
    {
        "id": 2,
        "state": "Running",
        "health": "Unknown",
        "description": "cyclictest",
        "actual_device": "bbb",
        "definition": "",
    },
]


def test_export_once(monkeypatch, tmp_path, capsys):
    sent = []
    monkeypatch.setattr(ex.LavaApi, "from_config", classmethod(lambda c, s: FakeApi()))
    monkeypatch.setattr(ex, "select_jobs", lambda *a: JOBS)
    monkeypatch.setattr(ex, "send", lambda cfg, body: sent.append(body))
    cfg = tmp_path / "metrics.yml"
    cfg.write_text("url: http://vm.lan:8427\n")
    system_config = {
        "database-path": str(tmp_path / "jobs.db"),
        "metrics-config": str(cfg),
    }
    args = SimpleNamespace(dry_run=False, force=False, no_artifacts=True)

    ex.cmd_jobs_export(args, system_config, {})
    assert len(sent) == 1 and '"job":"1"' in sent[0]  # the running job waits
    ex.cmd_jobs_export(args, system_config, {})
    assert len(sent) == 1
    assert "nothing to export" in capsys.readouterr().err
    args.force = True
    ex.cmd_jobs_export(args, system_config, {})
    assert len(sent) == 2
