"""The round archive: the results of the test rounds as plain files.

The master copy of the results (doc/ROUNDS.md): LAVA has no backup and
starts its job ids at 1 again when rebuilt, the uploads are deleted
from Artifactorial once archived, VictoriaMetrics is filled from here.
Plain files, so grep, diff, rsync and rm -r work without srt-build.
<round> is a release round (12) or test/<id> for a test round (test/t3):

  <archive>/<round>/round.yaml        what the round is (versions, jobs)
  <archive>/<round>/report.txt        format_report() of the round
  <archive>/<round>/jobs/<id>/job.json, tests.json, suites.json
                                      LAVA's answers, as LavaApi gets them
  <archive>/<round>/jobs/<id>/log.yaml.gz
  <archive>/<round>/jobs/<id>/uploads/<suite>/<name>.json
                                      per suite (5_rtla-timerlat): a combined
                                      job's tests upload the same names
  <archive>/<round>/jobs/<id>/uploads.yaml
                                      each upload's URL, size, and when it
                                      was deleted from Artifactorial
  <archive>/<round>/jobs/<id>/complete  written last: the job is whole

Every file is written to <name>.tmp and renamed, so an interrupted run
leaves no half file. The secrets in a job (the Artifactorial token in
its definition and log, LAVA's job token) are replaced before anything
is written.
"""

import gzip
import json
import os
import re
import urllib.request
from collections import Counter
from datetime import datetime, timezone

import yaml

from .metrics import job_metadata, uploads as upload_list

DEFAULT_ARCHIVE = "~/.local/share/srt-build/rounds"
FORMAT = 1
ARTIFACTORIAL_PLACEHOLDER = "<ARTIFACTORIAL_TOKEN>"
JOB_TOKEN_PLACEHOLDER = "<LAVA_JOB_TOKEN>"
_TOKEN_PARAM = re.compile(r"ARTIFACTORIAL_TOKEN['\"]?\s*:\s*['\"]?([^'\"\s,}]+)")


def archive_path(system_config):
    return os.path.expanduser(system_config.get("round-archive") or DEFAULT_ARCHIVE)


def now():
    """The time as round.yaml keeps it (UTC, like LAVA's)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_atomic(path, data):
    """Write data (str or bytes) to path through path.tmp."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    os.replace(tmp, path)


# Rounds


# Release rounds are numbered 10, 11, ... and kept at <archive>/<n>; test
# rounds (config experiments, partial rounds) t1, t2, ... at
# <archive>/test/t<n>. A round id is the text: "12" or "t3".
RELEASE, TEST = "release", "test"


def parse_round(text, test=False):
    """A round id from the command line: "12", "t3"; with test, "3" is
    "t3" too."""
    s = str(text).strip()
    if s[:1] == "t" and s[1:].isdigit() and int(s[1:]) > 0:
        return f"t{int(s[1:])}"
    if s.isdigit() and int(s) > 0:
        return f"t{int(s)}" if test else str(int(s))
    raise SystemExit(f"bad round {text!r}: a release round (12) or a test round (t3)")


def round_kind(rid):
    return TEST if str(rid).startswith("t") else RELEASE


def _number(rid):
    return int(str(rid).lstrip("t"))


def round_dir(archive, rid):
    rid = parse_round(rid)
    if round_kind(rid) == TEST:
        return os.path.join(archive, "test", rid)
    return os.path.join(archive, rid)


def round_ids(archive, kind=None):
    """The rounds in the archive: release rounds, then test rounds,
    each oldest first."""
    found = []
    for k, top in ((RELEASE, archive), (TEST, os.path.join(archive, "test"))):
        if kind not in (None, k) or not os.path.isdir(top):
            continue
        ids = [
            d
            for d in os.listdir(top)
            if (d.isdigit() if k == RELEASE else d[:1] == "t" and d[1:].isdigit())
            and os.path.exists(os.path.join(top, d, "round.yaml"))
        ]
        found += sorted(ids, key=_number)
    return found


def next_round(archive, kind=RELEASE):
    ids = round_ids(archive, kind)
    n = _number(ids[-1]) + 1 if ids else 1
    return f"t{n}" if kind == TEST else str(n)


def newest_round(archive):
    """The round started last, of either kind; None if there is none."""
    ids = round_ids(archive)
    if not ids:
        return None
    return max(ids, key=lambda r: (str(load_round(archive, r).get("started")), r))


def load_round(archive, rid):
    path = os.path.join(round_dir(archive, rid), "round.yaml")
    try:
        with open(path) as f:
            info = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise SystemExit(f"no round {rid} in {archive}") from None
    info["round"] = str(info["round"])
    info.setdefault("kind", round_kind(info["round"]))
    info["jobs"] = {int(k): v for k, v in (info.get("jobs") or {}).items()}
    info["reruns"] = {int(k): int(v) for k, v in (info.get("reruns") or {}).items()}
    return info


# round.yaml's keys in the order of doc/ROUNDS.md; others follow.
ORDER = (
    "format round kind lava started srt_build test_definitions kernel notes "
    "imported boards submissions jobs reruns reported exported"
).split()


def save_round(archive, info):
    """Write round.yaml whole, its keys in ORDER."""
    info = {k: v for k, v in info.items() if v not in (None, {}, [])}
    rank = {k: i for i, k in enumerate(ORDER)}
    info = dict(sorted(info.items(), key=lambda kv: rank.get(kv[0], len(ORDER))))
    if str(info["round"]).isdigit():
        info["round"] = int(info["round"])  # round: 12, round: t3
    if "jobs" in info:
        info["jobs"] = dict(sorted(info["jobs"].items()))
    # Block style at the top, a job's entry in one line.
    text = "".join(
        yaml.safe_dump(
            {k: v},
            sort_keys=False,
            default_flow_style=None if isinstance(v, (dict, list)) else False,
            width=100,
        )
        for k, v in info.items()
    )
    write_atomic(os.path.join(round_dir(archive, info["round"]), "round.yaml"), text)


def board_runs(archive, board):
    """[[job ids]] of the board in each round, by the rounds' start
    (`jobs results`, `jobs cancel`: "the board's last run")."""
    runs = []
    for rid in round_ids(archive):
        info = load_round(archive, rid)
        ids = [j for j in counted_jobs(info) if info["jobs"][j].get("board") == board]
        if ids:
            runs.append((str(info.get("started")), ids))
    return [ids for _, ids in sorted(runs)]


def counted_jobs(info):
    """The jobs that count: all of the round but those a rerun replaced."""
    return sorted(set(info.get("jobs") or {}) - set(info.get("reruns") or {}))


def job_entry(job):
    """What round.yaml says about a job: board, flavor and test, from
    its srt.* metadata."""
    md = job_metadata(job)
    words = (job.get("description") or "").split()
    return {
        "board": str(md.get("srt.board") or job.get("actual_device") or ""),
        "flavor": str(md.get("srt.flavor") or (words[1] if len(words) > 1 else "rt")),
        "test": str(md.get("srt.test") or (words[0] if words else "")),
    }


def new_round(rid, lava, jobs=(), **extra):
    """round.yaml of a round made of jobs (LAVA job objects) that
    already ran (`round import`), or of none yet (`round start`).
    extra: notes (free text, optional) and what round start adds."""
    mds = [job_metadata(j) for j in jobs]

    def common(key):
        values = Counter(str(m[key]) for m in mds if m.get(key))
        return values.most_common(1)[0][0] if values else None

    starts = sorted(j["submit_time"] for j in jobs if j.get("submit_time"))
    info = {
        "format": FORMAT,
        "round": parse_round(rid),
        "kind": round_kind(parse_round(rid)),
        "lava": lava,
        "started": _z(starts[0]) if starts else now(),
        "srt_build": common("srt.build"),
        "test_definitions": test_definitions(jobs),
        "kernel": common("srt.kernel"),
    }
    info.update(extra)
    info["boards"] = sorted(
        {job_entry(j)["board"] for j in jobs} | set(info.get("boards") or [])
    )
    info["jobs"] = {j["id"]: job_entry(j) for j in jobs}
    return info


def _z(stamp):
    """LAVA's "2026-11-13T12:40:01.123456Z" -> "2026-11-13T12:40:01Z"."""
    return str(stamp)[:19] + "Z"


def test_definitions(jobs):
    """{url, branch} of the git test definitions the jobs run."""
    for job in jobs:
        try:
            definition = yaml.safe_load(job.get("definition") or "") or {}
        except yaml.YAMLError:
            continue
        for action in definition.get("actions") or []:
            for d in ((action or {}).get("test") or {}).get("definitions") or []:
                if d.get("from") == "git":
                    out = {"url": d.get("repository")}
                    if d.get("branch"):
                        out["branch"] = d["branch"]
                    return out
    return None


def definitions_commit(tests):
    """The test-definitions commit LAVA checked out (commit_id of the
    lava suite's "<n>_<definition>" cases), None if there is none."""
    commits = Counter()
    for t in tests:
        md = t.get("metadata") or ""
        if "commit_id" not in md:
            continue
        try:
            md = yaml.safe_load(md) or {}
        except yaml.YAMLError:
            continue
        if isinstance(md, dict) and md.get("commit_id"):
            commits[str(md["commit_id"])] += 1
    return commits.most_common(1)[0][0] if commits else None


# Secrets


def secrets(job):
    """{secret: placeholder} of a job: the Artifactorial token, a
    parameter of its test definitions that shows up in the log's
    command lines too, and LAVA's own token of the job."""
    out = {}
    for key in ("definition", "original_definition", "multinode_definition"):
        for token in _TOKEN_PARAM.findall(str(job.get(key) or "")):
            if token != ARTIFACTORIAL_PLACEHOLDER and len(token) >= 8:
                out[token] = ARTIFACTORIAL_PLACEHOLDER
    if job.get("token") and job["token"] != JOB_TOKEN_PLACEHOLDER:
        out[str(job["token"])] = JOB_TOKEN_PLACEHOLDER
    return out


def scrub(data, found):
    """data (str or bytes) with every secret replaced."""
    for secret, placeholder in found.items():
        if isinstance(data, bytes):
            data = data.replace(secret.encode(), placeholder.encode())
        else:
            data = data.replace(secret, placeholder)
    return data


# Jobs


def job_dir(rdir, job_id):
    return os.path.join(rdir, "jobs", str(int(job_id)))


def is_complete(rdir, job_id):
    return os.path.exists(os.path.join(job_dir(rdir, job_id), "complete"))


def save_job(rdir, job, tests, suites, log, uploads, complete=True, urls=None):
    """Write a job into the round directory rdir, scrubbed.

    uploads: {"<suite name>/<file name>": bytes}. complete: write the
    marker that the job is whole (not if an upload is missing: fetch it
    again next time). urls: {"<suite name>/<file name>": URL}, for
    uploads.yaml.
    """
    jdir = job_dir(rdir, job["id"])
    found = secrets(job)
    for name, data in (("job", job), ("tests", tests), ("suites", suites)):
        text = scrub(json.dumps(data, indent=1), found)
        write_atomic(os.path.join(jdir, name + ".json"), text + "\n")
    log = scrub(log or "", found).encode("utf-8")
    write_atomic(os.path.join(jdir, "log.yaml.gz"), gzip.compress(log, mtime=0))
    records = {}
    for name, data in uploads.items():
        suite, _, fname = name.partition("/")
        path = os.path.join(jdir, "uploads", _safe_name(suite), _safe_name(fname))
        data = scrub(data, found)
        write_atomic(path, data)
        records[name] = {"url": (urls or {}).get(name), "size": len(data)}
    for name, url in (urls or {}).items():
        records.setdefault(name, {"url": url, "size": None})
    if records:
        save_upload_records(rdir, job["id"], records)
    if complete:
        write_atomic(os.path.join(jdir, "complete"), "")


def upload_paths(tests, suites):
    """[(name as metrics.artifact_urls() has it, "<suite name>/<file>",
    url)] of a job's JSON uploads."""
    names = {su["id"]: su["name"] for su in suites or []}
    return [
        (key, f"{names.get(sid, sid)}/{url.rsplit('/', 1)[-1]}", url)
        for key, sid, url in upload_list(tests)
    ]


def _safe_name(name):
    name = os.path.basename(str(name))
    if not name or name.startswith("."):
        raise ValueError(f"bad upload name {name!r}")
    return name


def fetch_url(url, timeout=60):
    """An upload's bytes; ValueError if it isn't JSON (an error page)."""
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = r.read()
    json.loads(data)
    return data


def fetch_job(api, rdir, job, fetch=None):
    """Fetch a finished job from LAVA (api) and its uploads into rdir.

    Returns the names of the uploads that couldn't be fetched; the job
    is complete only without any.
    """
    fetch = fetch or fetch_url
    jid = job["id"]
    tests = api.tests(jid)
    suites = api.suites(jid)
    log = api.log(jid)
    uploads, urls, missing = {}, {}, []
    for _, path, url in upload_paths(tests, suites):
        urls[path] = url
        try:
            uploads[path] = fetch(url)
        except (OSError, ValueError):
            missing.append(path)
    save_job(rdir, job, tests, suites, log, uploads, not missing, urls)
    return missing


def upload_records(rdir, job_id):
    """{"<suite>/<file>": {url, size, deleted}} of an archived job's
    uploads: uploads.yaml, or (rounds archived before it existed) what
    its test results and the files say."""
    jdir = job_dir(rdir, job_id)
    path = os.path.join(jdir, "uploads.yaml")
    if os.path.exists(path):
        with open(path) as f:
            return yaml.safe_load(f) or {}
    a = ArchiveApi(rdir)
    if not a.has(job_id):
        return {}
    out = {}
    for _, name, url in upload_paths(a.tests(job_id), a.suites(job_id)):
        local = os.path.join(jdir, "uploads", name)
        size = os.path.getsize(local) if os.path.exists(local) else None
        out[name] = {"url": url, "size": size}
    return out


def save_upload_records(rdir, job_id, records):
    text = yaml.safe_dump(records, sort_keys=True, default_flow_style=False)
    write_atomic(os.path.join(job_dir(rdir, job_id), "uploads.yaml"), text)


def verified_copy(rdir, job_id, name, record):
    """Whether the archive's copy of an upload is whole: there, the
    size it had when fetched, JSON."""
    path = os.path.join(job_dir(rdir, job_id), "uploads", name)
    try:
        with open(path, "rb") as f:
            data = f.read()
        json.loads(data)
    except (OSError, ValueError):
        return False
    return record.get("size") is None or len(data) == record["size"]


def delete_uploads(rdir, job_ids, token, delete_fn):
    """Delete the uploads of whole archived jobs from Artifactorial, each
    only once its copy is verified; uploads.yaml records it, so the next
    run doesn't ask again. Returns [(job id, name, result)]."""
    results = []
    for jid in job_ids:
        if not is_complete(rdir, jid):
            continue
        records = upload_records(rdir, jid)
        changed = False
        for name, rec in sorted(records.items()):
            if rec.get("deleted") or not rec.get("url"):
                continue
            if not verified_copy(rdir, jid, name, rec):
                results.append((jid, name, "kept: the copy doesn't verify"))
                continue
            try:
                result = delete_fn(rec["url"], token)
            except (OSError, ValueError) as exc:
                results.append((jid, name, f"failed: {exc}"))
                continue
            rec["deleted"] = now()
            changed = True
            results.append((jid, name, result))
        if changed:
            save_upload_records(rdir, jid, records)
    return results


def remaining_upload_urls(rdir, job_id):
    """URLs of an archived job's uploads not deleted yet."""
    return [
        r["url"]
        for r in upload_records(rdir, job_id).values()
        if r.get("url") and not r.get("deleted")
    ]


class ArchiveApi:
    """A round's archived jobs, read with the accessors of LavaApi, so
    report and metrics take them as they take LAVA's answers."""

    def __init__(self, rdir):
        self.rdir = rdir

    def _json(self, job_id, name):
        with open(os.path.join(job_dir(self.rdir, job_id), name)) as f:
            return json.load(f)

    def has(self, job_id):
        return os.path.exists(os.path.join(job_dir(self.rdir, job_id), "job.json"))

    def complete(self, job_id):
        return is_complete(self.rdir, job_id)

    def job(self, job_id):
        return self._json(job_id, "job.json")

    def tests(self, job_id):
        return self._json(job_id, "tests.json")

    def suites(self, job_id):
        return self._json(job_id, "suites.json")

    def log(self, job_id):
        path = os.path.join(job_dir(self.rdir, job_id), "log.yaml.gz")
        if not os.path.exists(path):
            return ""
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            return f.read()

    def uploads(self, job_id):
        """{file name: parsed JSON} of the job's uploads, named as
        metrics.artifact_urls() names them."""
        d = os.path.join(job_dir(self.rdir, job_id), "uploads")
        out = {}
        for key, path, _ in upload_paths(self.tests(job_id), self.suites(job_id)):
            suite, _, fname = path.partition("/")
            full = os.path.join(d, _safe_name(suite), _safe_name(fname))
            if os.path.exists(full):
                with open(full, "rb") as f:
                    out[key] = json.loads(f.read())
        return out
