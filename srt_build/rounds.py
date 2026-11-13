"""Rounds: what `lava`, `smoke` and `round start` share (doc/ROUNDS.md).

Every submission belongs to a round: `round start` makes a release
round (10, 11, ...), every `lava` or `smoke` command a test round (t1,
t2, ...) of its own. The round's round.yaml is written before the first
job is submitted and again as jobs come in; the archive is the only
record of what was submitted (there is no database).
"""

import subprocess
import sys
import urllib.parse

import yaml

from . import helpers
from .archive import (
    TEST,
    archive_path,
    load_round,
    new_round,
    next_round,
    round_ids,
    save_round,
)


def lava_instance(system_config, api=None):
    """The LAVA instance's name: job ids are only unique within one."""
    if system_config.get("lava-instance"):
        return system_config["lava-instance"]
    if api is None:
        from .lava_api import LavaApi

        api = LavaApi.from_config(system_config)
    return urllib.parse.urlsplit(api.base).hostname


def check_instance(info, system_config, api):
    here = lava_instance(system_config, api)
    if info.get("lava") and info["lava"] != here:
        raise SystemExit(
            f"round {info['round']} ran on {info['lava']}, LAVA here is {here}"
        )


def jobs_in_rounds(archive, lava, job_ids):
    """{job id: round} of those of job_ids that a round of LAVA instance
    lava has. A scan of every round.yaml: fast enough for hundreds of
    rounds; a cache can come when it isn't."""
    ids = {int(j) for j in job_ids}
    taken = {}
    for rid in round_ids(archive):
        info = load_round(archive, rid)
        if info.get("lava") == lava:
            taken.update({j: rid for j in info["jobs"] if j in ids})
    return taken


def duplicate_message(lava, rid, taken):
    """Why job ids can't go into round rid: taken = {job id: round}."""
    jobs = ", ".join(f"{j} (round {r})" for j, r in sorted(taken.items())[:10])
    return (
        f"round {rid}: job ids already in a round of LAVA instance {lava}: "
        f"{jobs}. Job ids are per instance: was LAVA reset (ids start at 1 "
        "again)? Then give it a new name, system_config lava-instance in "
        "config.yml."
    )


def check_new_jobs(archive, lava, rid, job_ids, own=()):
    """Refuse job ids a round of the same LAVA instance has: a job
    belongs to one round, and a reset LAVA hands out the same ids
    again. own: the round's jobs so far, which a new id mustn't be
    either."""
    taken = {
        j: r
        for j, r in jobs_in_rounds(archive, lava, job_ids).items()
        if str(r) != str(rid)
    }
    taken.update({int(j): rid for j in job_ids if int(j) in set(own)})
    if taken:
        raise SystemExit(duplicate_message(lava, rid, taken))


def kernel_describe():
    """git describe of the kernel tree (the current directory)."""
    try:
        r = subprocess.run(["git", "describe"], capture_output=True, text=True)
        return r.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def recording_submit(entries, dry_run=False):
    """A submit function for cmd_lava that notes board, flavor and test
    of every job (from its metadata): {job id: entry}; with dry_run it
    submits nothing and appends the entries to a list."""

    def submit(path, jobs):
        with open(path) as f:
            md = (yaml.safe_load(f) or {}).get("metadata") or {}
        entry = {k: str(md.get(f"srt.{k}", "")) for k in ("board", "flavor", "test")}
        if dry_run:
            entries.append(entry)
            jobs.append("dry-run")
            return
        n = len(jobs)
        helpers._submit(path, jobs)
        if len(jobs) > n and str(jobs[-1]).strip().isdigit():
            entries[int(jobs[-1])] = entry

    return submit


def add_jobs(system_config, info, ids, entries, board, submission=None):
    """Add submitted jobs to the round and write round.yaml."""
    archive = archive_path(system_config)
    check_new_jobs(archive, info["lava"], info["round"], ids, own=info["jobs"])
    blank = {"board": board, "flavor": "", "test": ""}
    for jid in ids:
        entry = dict(entries.get(jid) or blank)
        if submission is not None:
            entry["submission"] = submission
        info["jobs"][jid] = entry
    save_round(archive, info)


def begin_test_round(system_config, board, submission, kernel=None):
    """The test round of one `lava`/`smoke` command, written before its
    first job: round.yaml with the command's options as its one
    submission."""
    archive = archive_path(system_config)
    rid = next_round(archive, TEST)
    if rid in round_ids(archive):  # a second command at the same moment
        raise SystemExit(f"round {rid} exists already, try again")
    info = new_round(
        rid,
        lava_instance(system_config),
        srt_build=helpers.srt_build_version(),
        kernel=kernel or kernel_describe(),
    )
    info.update(boards=[board], submissions=[submission])
    save_round(archive, info)
    print(f"test round {rid}", file=sys.stderr)
    return info


def print_round(info):
    print(f"round {info['round']} ({info.get('kind')}), lava {info['lava']}")
    print(f"  srt-build {info.get('srt_build')}, kernel {info.get('kernel')}")
    for jid, e in sorted((info.get("jobs") or {}).items()):
        print(f"  {jid}  {e['board']}  {e['flavor']}  {e['test']}")
