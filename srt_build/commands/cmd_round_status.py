"""round status, round wait and round cancel - follow a round in LAVA.

  srt-build round status [N]        state and health of every job
  srt-build round wait [N]          until every job has finished
  srt-build round wait --batch N --report   each round of a batch
  srt-build round cancel N | --batch N      the jobs not finished

They ask LAVA (jobs the archive has whole are read from there). A job
a rerun replaced is shown with its replacement and waited for no
longer. `round wait` prints a line for every job that finishes not
Complete, as it happens, warns when the LAVA server's disk runs low,
and exits with 1 if a job ended not Complete; then `round report`.
With --batch it waits for the rounds of a batch (round start/repeat
--count) one after the other, in their order; --report reports each
round (`round report`) once it has finished, while the later ones are
still queued, and exits with 1 on problems too.

`round cancel` cancels the jobs of a round, or of every round of a
batch, which haven't finished, asking first; the rounds stay in the
archive (`round drop` removes one).
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor

from ..archive import ArchiveApi, counted_jobs, load_round, round_dir
from ..lava_api import LavaApi, rpc_from_lavacli
from ..rounds import check_instance
from .cmd_round import (
    add_batch_arg,
    add_json_arg,
    add_round_arg,
    confirm,
    pick_round,
    pick_rounds,
    print_json,
)
from .cmd_round_report import add_keep_uploads, report_round
from .cmd_round_start import LAVA_DISK_MIN_GB, lava_free_gb


def add_parsers(sub):
    p = sub.add_parser("status", help="state and health of a round's jobs")
    add_round_arg(p)
    add_json_arg(p)
    p.set_defaults(func=cmd_round_status)
    p = sub.add_parser("wait", help="wait until every job of a round finished")
    add_round_arg(p)
    add_batch_arg(p)
    p.add_argument("--interval", type=int, default=60, help="seconds between polls")
    p.add_argument(
        "--report",
        action="store_true",
        help="round report each round once it has finished",
    )
    add_keep_uploads(p)
    p.set_defaults(func=cmd_round_wait)
    p = sub.add_parser("cancel", help="cancel the jobs of a round not finished")
    add_round_arg(p)
    add_batch_arg(p)
    p.add_argument(
        "--dry-run", action="store_true", help="list the jobs, cancel nothing"
    )
    p.add_argument("--yes", action="store_true", help="don't ask")
    p.set_defaults(func=cmd_round_cancel)


def job_states(api, rdir, job_ids):
    """{job id: (state, health)}: from the archive if whole there."""
    a = ArchiveApi(rdir)

    def one(jid):
        job = a.job(jid) if a.complete(jid) else api.job(jid)
        return jid, (job.get("state", ""), job.get("health", ""))

    with ThreadPoolExecutor(8) as pool:
        return dict(pool.map(one, job_ids))


def cmd_round_status(args, system_config, machine_config):
    archive, rid = pick_round(args, system_config)
    info = load_round(archive, rid)
    api = LavaApi.from_config(system_config)
    check_instance(info, system_config, api)
    states = job_states(api, round_dir(archive, rid), sorted(info["jobs"]))
    rerun_of = {new: old for old, new in info["reruns"].items()}
    counts, jobs = {}, []
    for jid, (state, health) in sorted(states.items()):
        e = info["jobs"][jid]
        what = health if state == "Finished" else state
        if jid not in info["reruns"]:
            counts[what] = counts.get(what, 0) + 1
        jobs.append(
            {
                "id": jid,
                "board": e["board"],
                "flavor": e["flavor"],
                "test": e["test"],
                "state": state,
                "health": health,
                "replaced_by": info["reruns"].get(jid),
                "rerun_of": rerun_of.get(jid),
            }
        )
    free = lava_free_gb(system_config)
    if getattr(args, "json", False):
        print_json(
            {
                "round": str(rid),
                "jobs": jobs,
                "counts": counts,
                "finished": all(
                    j["state"] == "Finished" for j in jobs if not j["replaced_by"]
                ),
                "lava_disk_free_gb": free,
            }
        )
        return
    for j in jobs:
        what = j["health"] if j["state"] == "Finished" else j["state"]
        note = ""
        if j["replaced_by"]:
            note = f"  replaced by {j['replaced_by']}"
        elif j["rerun_of"]:
            note = f"  rerun of {j['rerun_of']}"
        print(f"{j['id']}  {j['board']:8} {j['flavor']:12} {j['test']:24} {what}{note}")
    summary = ", ".join(f"{n} {w}" for w, n in sorted(counts.items()))
    disk = "unknown" if free is None else f"{free}G"
    print(f"\nround {rid}: {summary}; LAVA disk free: {disk}")


def cmd_round_wait(args, system_config, machine_config, sleep=time.sleep):
    archive, rids = pick_rounds(args, system_config)
    api = LavaApi.from_config(system_config)
    failed = False
    for rid in rids:
        failed |= bool(wait_round(api, archive, rid, args, system_config, sleep))
        if getattr(args, "report", False):
            info = load_round(archive, rid)
            keep = getattr(args, "keep_uploads", False)
            summaries = report_round(api, system_config, archive, info, keep)
            failed |= any(s.problems() for s in summaries)
    if failed:
        sys.exit(1)


def wait_round(api, archive, rid, args, system_config, sleep):
    """Until every job of the round finished; the jobs not Complete."""
    check_instance(load_round(archive, rid), system_config, api)
    limit = int(system_config.get("lava-disk-min-gb", LAVA_DISK_MIN_GB))
    done, disk_warned = {}, False
    while True:
        info = load_round(archive, rid)  # a rerun may have come in
        todo = [j for j in counted_jobs(info) if j not in done]
        try:
            states = job_states(api, round_dir(archive, rid), todo)
        except OSError as exc:  # LAVA away longer than its retries
            print(f"warning: LAVA: {exc}; waiting on", file=sys.stderr)
            sleep(args.interval)
            continue
        for jid, (state, health) in states.items():
            if state != "Finished":
                continue
            done[jid] = health
            if health != "Complete":
                e = info["jobs"][jid]
                print(f"job {jid} {e['board']} {e['flavor']} {e['test']}: {health}")
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
    sys.stdout.flush()
    return bad


def cmd_round_cancel(args, system_config, machine_config):
    archive, rids = pick_rounds(args, system_config)
    api = LavaApi.from_config(system_config)
    todo = []
    for rid in rids:
        info = load_round(archive, rid)
        check_instance(info, system_config, api)
        states = job_states(api, round_dir(archive, rid), counted_jobs(info))
        for jid, (state, _) in sorted(states.items()):
            if state not in ("Finished", "Canceling"):
                todo.append((rid, jid, info["jobs"][jid], state))
    if not todo:
        print(f"round {', '.join(rids)}: no job left to cancel")
        return
    for rid, jid, e, state in todo:
        print(f"{rid}  {jid}  {e['board']:8} {e['flavor']:12} {e['test']:24} {state}")
    if getattr(args, "dry_run", False):
        return
    if not confirm(f"cancel these {len(todo)} jobs?", getattr(args, "yes", False)):
        raise SystemExit("nothing canceled")
    rpc = rpc_from_lavacli(identity=system_config.get("lava-identity", "default"))
    for _, jid, _, _ in todo:
        rpc.scheduler.jobs.cancel(jid)
    print(f"{len(todo)} jobs canceled; the rounds stay in the archive "
          f"(round drop removes one)")  # fmt: skip
