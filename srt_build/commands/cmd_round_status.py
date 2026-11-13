"""round status and round wait - follow a round in LAVA.

  srt-build round status [N]        state and health of every job
  srt-build round wait [N]          until every job has finished

Both ask LAVA (jobs the archive has whole are read from there). A job
a rerun replaced is shown with its replacement and waited for no
longer. `round wait` prints a line for every job that finishes not
Complete, as it happens, warns when the LAVA server's disk runs low,
and exits with 1 if a job ended not Complete; then `round report`.
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor

from ..archive import ArchiveApi, counted_jobs, load_round, round_dir
from ..lava_api import LavaApi
from ..rounds import check_instance
from .cmd_round import add_round_arg, pick_round
from .cmd_round_start import LAVA_DISK_MIN_GB, lava_free_gb


def add_parsers(sub):
    p = sub.add_parser("status", help="state and health of a round's jobs")
    add_round_arg(p)
    p.set_defaults(func=cmd_round_status)
    p = sub.add_parser("wait", help="wait until every job of a round finished")
    add_round_arg(p)
    p.add_argument("--interval", type=int, default=60, help="seconds between polls")
    p.set_defaults(func=cmd_round_wait)


def job_states(api, rdir, job_ids):
    """{job id: (state, health)}: from the archive if whole there."""
    a = ArchiveApi(rdir)

    def one(jid):
        job = a.job(jid) if a.complete(jid) else api.job(jid)
        return jid, (job.get("state", ""), job.get("health", ""))

    with ThreadPoolExecutor(8) as pool:
        return dict(pool.map(one, job_ids))


def _disk(system_config):
    free = lava_free_gb(system_config)
    return "unknown" if free is None else f"{free}G"


def cmd_round_status(args, system_config, machine_config):
    archive, rid = pick_round(args, system_config)
    info = load_round(archive, rid)
    api = LavaApi.from_config(system_config)
    check_instance(info, system_config, api)
    states = job_states(api, round_dir(archive, rid), sorted(info["jobs"]))
    rerun_of = {new: old for old, new in info["reruns"].items()}
    counts = {}
    for jid, (state, health) in sorted(states.items()):
        e = info["jobs"][jid]
        what = health if state == "Finished" else state
        note = ""
        if jid in info["reruns"]:
            note = f"  replaced by {info['reruns'][jid]}"
        elif jid in rerun_of:
            note = f"  rerun of {rerun_of[jid]}"
        if jid not in info["reruns"]:
            counts[what] = counts.get(what, 0) + 1
        print(f"{jid}  {e['board']:8} {e['flavor']:12} {e['test']:24} {what}{note}")
    summary = ", ".join(f"{n} {w}" for w, n in sorted(counts.items()))
    print(f"\nround {rid}: {summary}; LAVA disk free: {_disk(system_config)}")


def cmd_round_wait(args, system_config, machine_config, sleep=time.sleep):
    archive, rid = pick_round(args, system_config)
    api = LavaApi.from_config(system_config)
    check_instance(load_round(archive, rid), system_config, api)
    limit = int(system_config.get("lava-disk-min-gb", LAVA_DISK_MIN_GB))
    done, bad, disk_warned = {}, [], False
    while True:
        info = load_round(archive, rid)  # a rerun may have come in
        todo = [j for j in counted_jobs(info) if j not in done]
        for jid, (state, health) in job_states(
            api, round_dir(archive, rid), todo
        ).items():
            if state != "Finished":
                continue
            done[jid] = health
            if health != "Complete":
                e = info["jobs"][jid]
                print(f"job {jid} {e['board']} {e['flavor']} {e['test']}: {health}")
                bad.append(jid)
        left = [j for j in counted_jobs(info) if j not in done]
        if not left:
            break
        free = lava_free_gb(system_config)
        if free is not None and free < limit and not disk_warned:
            print(f"warning: the LAVA server has {free}G free", file=sys.stderr)
            disk_warned = True
        sleep(args.interval)
    counted = counted_jobs(info)
    bad = [j for j in counted if done.get(j) != "Complete"]
    print(f"round {rid}: {len(counted)} jobs finished, {len(bad)} not Complete")
    if bad:
        sys.exit(1)
