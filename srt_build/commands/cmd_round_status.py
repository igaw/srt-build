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
still queued, and exits with 1 on problems too. While it waits it
shows where the round is (progress.py): finished, running and queued
jobs, the time so far and, from the jobs' durations in earlier rounds,
about how long is left; on a terminal in one line updated in place,
else a line when the counts change. --quiet turns that off.

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
from ..progress import (
    QUEUED,
    Progress,
    clock,
    duration,
    job_history,
    jobs_left,
    parse_time,
    wait_line,
)

# a batch's later rounds are asked for at most this often
LATER_SECONDS = 300


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
    p.add_argument(
        "--quiet", action="store_true", help="no progress, only what goes wrong"
    )
    p.set_defaults(func=cmd_round_wait)
    p = sub.add_parser("cancel", help="cancel the jobs of a round not finished")
    add_round_arg(p)
    add_batch_arg(p)
    p.add_argument(
        "--dry-run", action="store_true", help="list the jobs, cancel nothing"
    )
    p.add_argument("--yes", action="store_true", help="don't ask")
    p.set_defaults(func=cmd_round_cancel)


def job_states(api, rdir, job_ids, times=False):
    """{job id: (state, health)}, with times (state, health, start
    time): from the archive if whole there."""
    a = ArchiveApi(rdir)

    def one(jid):
        job = a.job(jid) if a.complete(jid) else api.job(jid)
        state = (job.get("state", ""), job.get("health", ""))
        if times:
            state += (parse_time(job.get("start_time")),)
        return jid, state

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
    progress = Progress(quiet=getattr(args, "quiet", False))
    batch = getattr(args, "batch", None) is not None
    failed, finished, bad = False, 0, 0
    for i, rid in enumerate(rids):
        where = None
        if batch:
            where = {
                "first": rids[0],
                "index": i + 1,
                "rounds": len(rids),
                "done": (finished, bad),
                "later": rids[i + 1 :],
            }
        not_complete = wait_round(
            api, archive, rid, args, system_config, sleep, progress, where
        )
        failed |= bool(not_complete)
        finished += len(counted_jobs(load_round(archive, rid)))
        bad += len(not_complete)
        if getattr(args, "report", False):
            info = load_round(archive, rid)
            keep = getattr(args, "keep_uploads", False)
            summaries = report_round(api, system_config, archive, info, keep)
            failed |= any(s.problems() for s in summaries)
    if failed:
        sys.exit(1)


def _key(entry):
    return (entry.get("board"), entry.get("flavor"), entry.get("test"))


class Waiting:
    """What round wait knows of a round (and the later rounds of its
    batch) for the progress line."""

    def __init__(self, api, archive, rid, where):
        self.api, self.archive, self.rid, self.where = api, archive, rid, where
        info = load_round(archive, rid)
        self.later = {r: load_round(archive, r) for r in (where or {}).get("later", [])}
        keys = {_key(info["jobs"][j]) for j in counted_jobs(info)}
        for other in self.later.values():
            keys |= {_key(other["jobs"][j]) for j in counted_jobs(other)}
        self.started = parse_time(info.get("started"))
        self.batch_started = self.started
        if where:
            first = load_round(archive, where["first"])
            self.batch_started = parse_time(first.get("started"))
        self.history = job_history(archive, self.started, info.get("kind"), keys)
        self.later_states, self.later_asked = {}, None

    def later_jobs(self, now):
        """(finished, not Complete, total, pending jobs) of the later
        rounds, asked at most every LATER_SECONDS."""
        if self.later and (
            self.later_asked is None or now - self.later_asked >= LATER_SECONDS
        ):
            states = {}
            for r, info in self.later.items():
                jobs = job_states(
                    self.api, round_dir(self.archive, r), counted_jobs(info), True
                )
                states.update({(r, j): st for j, st in jobs.items()})
            self.later_states, self.later_asked = states, now
        finished = bad = total = 0
        pending = []
        for r, info in self.later.items():
            for j in counted_jobs(info):
                total += 1
                state, health, start = self.later_states.get((r, j), ("", "", None))
                if state == "Finished":
                    finished += 1
                    bad += health != "Complete"
                else:
                    pending.append((*_key(info["jobs"][j]), state or QUEUED[0], start))
        return finished, bad, total, pending

    def line(self, info, done, states, now):
        """The progress line and what counts as a change."""
        counted = counted_jobs(info)
        pending, running, queued = [], 0, 0
        for j in counted:
            if j in done:
                continue
            state, _, start = states.get(j, (QUEUED[0], "", None))
            if state in QUEUED:
                queued += 1
            else:
                running += 1
            pending.append((*_key(info["jobs"][j]), state, start))
        bad = sum(1 for j in counted if j in done and done[j] != "Complete")
        counts = (len(counted) - len(pending), len(counted), bad, running, queued)
        if not self.where:
            elapsed = None if self.started is None else now - self.started
            left = jobs_left(pending, self.history, now)
            return wait_line(self.rid, counts, elapsed, left), counts
        w = self.where
        lf, lbad, ltotal, lpending = self.later_jobs(now)
        b_finished = w["done"][0] + counts[0] + lf
        b_bad = w["done"][1] + bad + lbad
        b_total = w["done"][0] + len(counted) + ltotal
        left = jobs_left(pending + lpending, self.history, now)
        text = wait_line(
            self.rid, counts, None, None, (w["first"], w["index"], w["rounds"])
        )
        text += f"; batch {b_finished}/{b_total} finished"
        if b_bad:
            text += f" ({b_bad} not Complete)"
        if self.batch_started is not None:
            text += f", {duration(now - self.batch_started)} so far"
        if left is not None:
            text += f", about {duration(left)} left"
        return text, (counts, b_finished, b_bad)


def wait_round(
    api, archive, rid, args, system_config, sleep, progress=None, where=None
):
    """Until every job of the round finished; the jobs not Complete.
    where: the batch it is in (cmd_round_wait), for the progress line."""
    check_instance(load_round(archive, rid), system_config, api)
    progress = progress or Progress(quiet=True)
    view = Waiting(api, archive, rid, where) if not progress.quiet else None
    limit = int(system_config.get("lava-disk-min-gb", LAVA_DISK_MIN_GB))
    done, disk_warned = {}, False
    while True:
        info = load_round(archive, rid)  # a rerun may have come in
        todo = [j for j in counted_jobs(info) if j not in done]
        try:
            states = job_states(api, round_dir(archive, rid), todo, True)
        except OSError as exc:  # LAVA away longer than its retries
            progress.message(f"warning: LAVA: {exc}; waiting on", file=sys.stderr)
            sleep(args.interval)
            continue
        for jid, (state, health, _) in states.items():
            if state != "Finished":
                continue
            done[jid] = health
            if health != "Complete":
                e = info["jobs"][jid]
                progress.message(
                    f"job {jid} {e['board']} {e['flavor']} {e['test']}: {health}"
                )
        left = [j for j in counted_jobs(info) if j not in done]
        if not left:
            break
        free = lava_free_gb(system_config)
        if free is not None and free < limit and not disk_warned:
            progress.message(
                f"warning: the LAVA server has {free}G free", file=sys.stderr
            )
            disk_warned = True
        if view is not None:
            try:
                text, key = view.line(info, done, states, clock())
                progress.show(text, key)
            except OSError:  # a later round of the batch: next time
                pass
        sleep(args.interval)
    progress.clear()
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
