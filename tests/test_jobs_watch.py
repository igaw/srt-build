"""jobs watch reports a job as it finishes, console findings included."""

from srt_build.commands.cmd_jobs_watch import _Round

STALL = (
    '- {"dt": "2026-11-11T13:04:38", "lvl": "target", "msg": '
    '"[   43.947336] rcu: INFO: rcu_preempt self-detected stall on CPU"}\n'
)


class FakeApi:
    def tests(self, job_id):
        return [{"name": "pi-stress", "result": "pass", "suite": "1_pi-stress"}]

    def suites(self, job_id):
        return []

    def log(self, job_id):
        return STALL


def test_console_findings_while_watching(capsys):
    job = {
        "id": 260,
        "actual_device": "c2d",
        "description": "pi-stress",
        "state": "Finished",
        "health": "Complete",
    }
    _Round().update(FakeApi(), [job], verbose=False)
    assert "job 260 c2d pi-stress: 1 console findings" in capsys.readouterr().out
