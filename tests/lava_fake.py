"""A LAVA for the round commands' tests: jobs with srt.* metadata, an
Artifactorial token in their definition and log, results and uploads."""

import json

TOKEN = "FAKEartifactorialTOKEN0123456789"
JOB_TOKEN = "FAKEjobTOKENabcdefabcdef01234567"


def definition(board, flavor, test, round=None):
    rnd = f'  srt.round: "{round}"\n' if round is not None else ""
    return f"""job_name: {test}{'' if flavor == 'rt' else ' ' + flavor}
metadata:
  srt.board: "{board}"
  srt.flavor: "{flavor}"
  srt.test: "{test}"
  srt.kernel: "v6.12.117-rt23"
  srt.build: "9e82b80d6821"
{rnd}actions:
- test:
    definitions:
    - from: git
      repository: git://lava.lan/test-definitions.git
      branch: rt-tests-fixes
      name: {test}
      parameters:
        ARTIFACTORIAL_TOKEN: {TOKEN}
        BACKGROUND_CMD: hackbench
"""


def job(jid, board="bbb", flavor="rt", test="cyclictest", state="Finished",
        health="Complete", round=None):  # fmt: skip
    return {
        "id": jid,
        "description": test if flavor == "rt" else f"{test} {flavor}",
        "actual_device": board,
        "state": state,
        "health": health if state == "Finished" else "Unknown",
        "health_check": False,
        "submit_time": f"2026-11-13T12:{jid % 60:02d}:01.5Z",
        "end_time": f"2026-11-13T14:{jid % 60:02d}:01.5Z",
        "definition": definition(board, flavor, test, round),
        "token": JOB_TOKEN,
    }


def tests(jid, latency=42):
    return [
        {
            "name": "1_cyclictest",
            "suite": 1,
            "result": "pass",
            "measurement": None,
            "unit": "",
            "metadata": "case: 1_cyclictest\ncommit_id: f6a8ad13\n",
        },
        {
            "name": "t0-max-latency",
            "suite": 2,
            "result": "pass",
            "measurement": str(latency),
            "unit": "us",
            "metadata": "",
        },
        {
            "name": "t0-avg-latency",
            "suite": 2,
            "result": "pass",
            "measurement": "7",
            "unit": "us",
            "metadata": "",
        },
        {
            "name": "test-attachment",
            "suite": 2,
            "result": "pass",
            "measurement": None,
            "unit": "",
            "metadata": f"reference: http://artifactorial.invalid/artifacts/rt-tests/{jid}/cyclictest.json\n",
        },
    ]


SUITES = [{"id": 1, "name": "lava"}, {"id": 2, "name": "1_cyclictest"}]


def log(jid):
    return (
        '- {"dt": "x", "lvl": "target", "msg": "Linux version 6.12.117-rt23"}\n'
        f'- {{"dt": "x", "lvl": "target", "msg": "curl -H token:{TOKEN} {jid}"}}\n'
    )


def upload(url):
    hist = {"3": 10, "40": 2}
    return json.dumps({"thread": {"0": {"histogram": hist, "cycles": 12}}}).encode()


class FakeLava:
    """LavaApi's accessors on the jobs given; counts what was asked."""

    base = "http://lava.test:10070/api/v0.2/"

    def __init__(self, jobs, latencies=None):
        self.jobs = {j["id"]: j for j in jobs}
        self.latencies = latencies or {}
        self.asked = []

    def job(self, jid):
        self.asked.append(("job", jid))
        return dict(self.jobs[jid])

    def tests(self, jid):
        self.asked.append(("tests", jid))
        return tests(jid, self.latencies.get(jid, 42))

    def suites(self, jid):
        return SUITES

    def log(self, jid):
        return log(jid)
