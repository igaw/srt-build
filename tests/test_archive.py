"""archive: a round's jobs as plain files, scrubbed of secrets, read
back like LAVA's answers."""

import gzip
import json
import os

import pytest
import yaml

from srt_build import archive

TOKEN = "FAKEartifactorialTOKEN0123456789"
JOB_TOKEN = "FAKEjobTOKENabcdefabcdef01234567"
URL = "http://artifactory.lan:8000/artifacts/team/rt/cyclictest.json"

DEFINITION = f"""
job_name: cyclictest
metadata:
  srt.board: bbb
  srt.flavor: rt
  srt.test: cyclictest
  srt.kernel: v6.12.117-rt23
  srt.build: 9e82b80d6821
actions:
- test:
    definitions:
    - from: git
      repository: git://lava.lan/test-definitions.git
      branch: rt-tests-fixes
      name: cyclictest
      parameters:
        ARTIFACTORIAL_TOKEN: {TOKEN}
        BACKGROUND_CMD: hackbench
"""


def make_job(jid=912, state="Finished", health="Complete"):
    return {
        "id": jid,
        "description": "cyclictest",
        "actual_device": "bbb",
        "state": state,
        "health": health,
        "submit_time": "2026-11-13T12:40:01.123456Z",
        "end_time": "2026-11-13T13:40:01.123456Z",
        "definition": DEFINITION,
        "original_definition": DEFINITION,
        "token": JOB_TOKEN,
    }


TESTS = [
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
        "measurement": "42",
        "unit": "us",
        "metadata": "",
    },
    {
        "name": "test-attachment",
        "suite": 2,
        "result": "pass",
        "measurement": None,
        "unit": "",
        "metadata": f"reference: {URL}\n",
    },
]
SUITES = [{"id": 1, "name": "lava"}, {"id": 2, "name": "1_cyclictest"}]
UPLOAD2 = json.dumps({"thread": {"0": {"histogram": {"9": 1}, "cycles": 1}}})
LOG = (
    '- {"dt": "x", "lvl": "target", "msg": "Linux version 6.12.117-rt23"}\n'
    f'- {{"dt": "x", "lvl": "target", "msg": "curl -H token:{TOKEN} up"}}\n'
)
UPLOAD = json.dumps({"thread": {"0": {"histogram": {"3": 10}, "cycles": 10}}})


class FakeApi:
    def __init__(self, jobs):
        self.jobs = {j["id"]: j for j in jobs}

    def job(self, jid):
        return self.jobs[jid]

    def tests(self, jid):
        return TESTS

    def suites(self, jid):
        return SUITES

    def log(self, jid):
        return LOG


def all_bytes(top):
    for root, _, files in os.walk(top):
        for name in files:
            with open(os.path.join(root, name), "rb") as f:
                data = f.read()
            if name.endswith(".gz"):
                data = gzip.decompress(data)
            yield os.path.join(root, name), data


def test_no_file_has_a_secret(tmp_path):
    job = make_job()
    missing = archive.fetch_job(
        FakeApi([job]), str(tmp_path), job, fetch=lambda url: UPLOAD.encode()
    )
    assert missing == []
    files = dict(all_bytes(tmp_path))
    assert str(tmp_path / "jobs/912/uploads/1_cyclictest/cyclictest.json") in files
    assert len(files) == 7  # with uploads.yaml
    for path, data in files.items():
        assert TOKEN.encode() not in data, path
        assert JOB_TOKEN.encode() not in data, path
    a = archive.ArchiveApi(str(tmp_path))
    assert archive.ARTIFACTORIAL_PLACEHOLDER in a.log(912)
    assert archive.ARTIFACTORIAL_PLACEHOLDER in a.job(912)["definition"]
    assert a.job(912)["token"] == archive.JOB_TOKEN_PLACEHOLDER


def test_read_back_like_lava(tmp_path):
    job = make_job()
    archive.fetch_job(
        FakeApi([job]), str(tmp_path), job, fetch=lambda url: UPLOAD.encode()
    )
    a = archive.ArchiveApi(str(tmp_path))
    assert a.complete(912)
    assert a.tests(912) == TESTS
    assert a.suites(912) == SUITES
    assert a.log(912) == LOG.replace(TOKEN, archive.ARTIFACTORIAL_PLACEHOLDER)
    assert a.uploads(912) == {"cyclictest.json": json.loads(UPLOAD)}
    assert not [p for p, _ in all_bytes(tmp_path) if p.endswith(".tmp")]


def test_missing_upload_leaves_job_unfinished(tmp_path):
    def fail(url):
        raise OSError("gone")

    job = make_job()
    assert archive.fetch_job(FakeApi([job]), str(tmp_path), job, fetch=fail) == [
        "1_cyclictest/cyclictest.json"
    ]
    a = archive.ArchiveApi(str(tmp_path))
    assert a.has(912) and not a.complete(912)


def test_round_yaml(tmp_path):
    info = archive.new_round(12, "lava.lan", [make_job(913), make_job(912)])
    assert info["started"] == "2026-11-13T12:40:01Z"
    assert info["srt_build"] == "9e82b80d6821"
    assert info["kernel"] == "v6.12.117-rt23"
    assert info["boards"] == ["bbb"]
    assert info["test_definitions"] == {
        "url": "git://lava.lan/test-definitions.git",
        "branch": "rt-tests-fixes",
    }
    assert info["jobs"][912] == {"board": "bbb", "flavor": "rt", "test": "cyclictest"}
    info["reruns"] = {913: 914}
    archive.save_round(str(tmp_path), info)
    text = (tmp_path / "12" / "round.yaml").read_text()
    assert text.startswith("format: 1\nround: 12\n")
    assert "912: {board: bbb, flavor: rt, test: cyclictest}" in text
    back = archive.load_round(str(tmp_path), 12)
    assert back == info
    assert archive.counted_jobs(back) == [912]
    assert archive.round_ids(str(tmp_path)) == ["12"]
    assert archive.next_round(str(tmp_path)) == "13"
    assert archive.next_round(str(tmp_path), archive.TEST) == "t1"
    assert yaml.safe_load(text)["started"] == "2026-11-13T12:40:01Z"


def test_definitions_commit():
    assert archive.definitions_commit(TESTS) == "f6a8ad13"
    assert archive.definitions_commit([]) is None


def test_same_name_from_two_suites(tmp_path):
    """A combined job: two tests upload rtla-timerlat.json, both kept,
    each under its suite, read back as metrics names them."""
    suites = SUITES + [{"id": 3, "name": "3_rtla-timerlat"}]
    tests = TESTS[:2] + [
        {
            **TESTS[2],
            "suite": 2,
            "metadata": "reference: http://a/1/rtla-timerlat.json",
        },
        {
            **TESTS[2],
            "suite": 3,
            "metadata": "reference: http://a/2/rtla-timerlat.json",
        },
    ]
    job = make_job()
    archive.save_job(
        str(tmp_path),
        job,
        tests,
        suites,
        LOG,
        {
            "1_cyclictest/rtla-timerlat.json": UPLOAD.encode(),
            "3_rtla-timerlat/rtla-timerlat.json": UPLOAD2.encode(),
        },
    )
    a = archive.ArchiveApi(str(tmp_path))
    assert a.uploads(912) == {
        "2-rtla-timerlat.json": json.loads(UPLOAD),
        "3-rtla-timerlat.json": json.loads(UPLOAD2),
    }


def test_release_and_test_rounds(tmp_path):
    top = str(tmp_path)
    for rid, started in (("10", "2026-11-12T08:00:00Z"), ("t2", "2026-11-14T09:00:00Z"),
                         ("9", "2026-11-11T08:00:00Z")):  # fmt: skip
        archive.save_round(
            top, {**archive.new_round(rid, "lava.lan"), "started": started}
        )
    assert (tmp_path / "test" / "t2" / "round.yaml").exists()
    assert (tmp_path / "10" / "round.yaml").exists()
    assert archive.round_ids(top) == ["9", "10", "t2"]
    assert archive.round_ids(top, archive.TEST) == ["t2"]
    assert archive.next_round(top) == "11"
    assert archive.next_round(top, archive.TEST) == "t3"
    assert archive.newest_round(top) == "t2"
    info = archive.load_round(top, "t2")
    assert info["round"] == "t2" and info["kind"] == "test"
    assert archive.load_round(top, "10")["kind"] == "release"
    assert "round: 10\nkind: release\n" in (tmp_path / "10" / "round.yaml").read_text()
    assert archive.parse_round("3", test=True) == "t3"
    assert archive.parse_round("t03") == "t3"
    with pytest.raises(SystemExit):
        archive.parse_round("x1")


def test_delete_uploads_once_verified(tmp_path):
    job = make_job()
    archive.fetch_job(
        FakeApi([job]), str(tmp_path), job, fetch=lambda url: UPLOAD.encode()
    )
    rdir = str(tmp_path)
    assert archive.remaining_upload_urls(rdir, 912) == [URL]
    asked = []

    def fake(url, token):
        asked.append((url, token))
        return "deleted"

    assert archive.delete_uploads(rdir, [912], "tok", fake) == [
        (912, "1_cyclictest/cyclictest.json", "deleted")
    ]
    assert asked == [(URL, "tok")]
    rec = archive.upload_records(rdir, 912)["1_cyclictest/cyclictest.json"]
    assert rec["deleted"] and rec["size"] == len(UPLOAD)
    assert archive.remaining_upload_urls(rdir, 912) == []
    # Done: not asked again.
    assert archive.delete_uploads(rdir, [912], "tok", fake) == []
    assert len(asked) == 1


def test_bad_copy_is_not_deleted(tmp_path):
    job = make_job()
    archive.fetch_job(
        FakeApi([job]), str(tmp_path), job, fetch=lambda url: UPLOAD.encode()
    )
    path = tmp_path / "jobs/912/uploads/1_cyclictest/cyclictest.json"
    path.write_bytes(UPLOAD.encode()[:-3])

    def fake(url, token):
        raise AssertionError("deleted")

    result = archive.delete_uploads(str(tmp_path), [912], "tok", fake)
    assert result == [(912, "1_cyclictest/cyclictest.json",
                       "kept: the copy doesn't verify")]  # fmt: skip
