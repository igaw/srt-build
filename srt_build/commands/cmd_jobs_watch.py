"""Jobs watch command - follow a test round until it is done.

Prints a line for every job that finishes with a problem (all jobs
with --verbose) and the progress, and ends with the full report once
every job has finished and no new job appeared for --settle seconds
(srt-build submits board by board, as each kernel is built).

  srt-build jobs watch --since 12
  srt-build jobs watch bbb --save ~/lava-runs/r4

Exits like `jobs report`: 1 if any job has a problem.
"""

import sys
import time

from ..lava_api import LavaApi
from ..report import summarize_job
from .cmd_jobs_report import (
    add_selection_args,
    fetch_summaries,
    print_report,
    select_jobs,
)


def add_parser(subparser):
    p = subparser.add_parser(
        "watch", help="follow the jobs of a test round, report when done"
    )
    add_selection_args(p)
    p.add_argument(
        "--interval", type=int, default=60, help="seconds between polls (60)"
    )
    p.add_argument(
        "--settle",
        type=int,
        default=600,
        help="seconds without new jobs before the round counts as done (600)",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="every job")
    p.add_argument("--save", metavar="DIR", help="save everything, as in report")
    p.add_argument("--no-report", action="store_true", help="no report at the end")
    p.set_defaults(func=cmd_jobs_watch)
    return p


def _line(s):
    problems = s.problems()
    text = "; ".join(problems) if problems else s.health
    return f"job {s.id} {s.device} {s.description}: {text}"


class _Round:
    """What the watch has seen so far."""

    def __init__(self):
        self.reported = set()
        self.known = set()
        self.last_change = time.monotonic()

    def quiet_for(self):
        return time.monotonic() - self.last_change

    def update(self, api, jobs, verbose):
        """Note new jobs, print the ones that finished since the last poll."""
        ids = {j["id"] for j in jobs}
        if ids - self.known:
            self.known |= ids
            self.last_change = time.monotonic()
        for job in jobs:
            if job["state"] != "Finished" or job["id"] in self.reported:
                continue
            try:
                s = summarize_job(job, api.tests(job["id"]), api.suites(job["id"]))
            except OSError:
                continue  # try again next poll
            self.reported.add(job["id"])
            self.last_change = time.monotonic()
            if verbose or s.problems():
                print(_line(s), flush=True)
            if len(self.reported) % 10 == 0:
                print(f"{len(self.reported)} of {len(ids)} jobs finished", flush=True)


def cmd_jobs_watch(args, system_config, machine_config):
    api = LavaApi.from_config(system_config)
    seen = _Round()
    while True:
        try:
            jobs = select_jobs(api, args, system_config, machine_config)
        except OSError as exc:  # LAVA restarting, network hiccup
            print(f"(LAVA not reachable: {exc}; retrying)", flush=True)
            time.sleep(args.interval)
            continue
        seen.update(api, jobs, args.verbose)
        done = jobs and all(j["state"] == "Finished" for j in jobs)
        if done and seen.quiet_for() >= args.settle:
            break
        time.sleep(args.interval)

    print(f"all {len(jobs)} jobs finished", flush=True)
    if args.no_report:
        return
    print()
    summaries = fetch_summaries(api, jobs, save=args.save)
    print_report(summaries, save=args.save)
    if any(s.problems() for s in summaries):
        sys.exit(1)
