"""Jobs report command - one table for all jobs of a test round.

  srt-build jobs report                 latest run of every board
  srt-build jobs report bbb c2d         latest run of these boards
  srt-build jobs report --since 12      every LAVA job after job 12
  srt-build jobs report --ids 13-72     these jobs
  srt-build jobs report --save DIR      also keep logs and results

"Latest run" is the last batch of jobs srt-build submitted for the
board, from its job database. --since and --ids ask LAVA instead, so
they also cover jobs submitted from another machine.

Exits with 1 if any job has a problem, 0 otherwise.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from ..database import get_job_list_from_db, get_jobs_from_db
from ..lava_api import LavaApi
from ..report import format_report, parse_id_list, summarize_job


def add_selection_args(p):
    """Arguments that pick the jobs; shared with `jobs watch`."""
    p.add_argument(
        "machines",
        nargs="*",
        help="boards to include (default: all boards in config.yml)",
    )
    sel = p.add_mutually_exclusive_group()
    sel.add_argument(
        "--since",
        type=int,
        metavar="ID",
        help="all LAVA jobs after job ID, not srt-build's job database",
    )
    sel.add_argument("--ids", metavar="LIST", help="these LAVA jobs, e.g. 13-72,80")
    p.add_argument(
        "--health-checks",
        action="store_true",
        help="include LAVA health checks (left out by default)",
    )


def add_parser(subparser):
    p = subparser.add_parser(
        "report", help="summarize the jobs of a test round across boards"
    )
    add_selection_args(p)
    p.add_argument(
        "--save", metavar="DIR", help="save job, results and log of every job"
    )
    p.add_argument(
        "--no-logs",
        action="store_true",
        help="don't fetch the logs (faster; no console findings)",
    )
    p.add_argument("--json", action="store_true", help="print JSON, not a table")
    p.set_defaults(func=cmd_jobs_report)
    return p


def _hostnames(args, machine_config):
    names = args.machines or list(machine_config)
    unknown = [m for m in names if m not in machine_config]
    if unknown:
        raise SystemExit(f"unknown board(s): {', '.join(unknown)}")
    return {machine_config[m].get("hostname", m): m for m in names}


def select_jobs(api, args, system_config, machine_config):
    """The jobs to look at, as REST job objects, oldest first."""
    hosts = _hostnames(args, machine_config)
    if args.since is not None:
        jobs = api.jobs_after(args.since)
    else:
        if args.ids:
            ids = parse_id_list(args.ids)
        else:
            ids = set()
            for m in hosts.values():
                runs = get_job_list_from_db(m, system_config)
                if runs:
                    ids.update(get_jobs_from_db(m, runs[-1], system_config, True))
        with ThreadPoolExecutor(8) as pool:
            jobs = list(pool.map(api.job, sorted(ids)))

    if not args.health_checks:
        jobs = [j for j in jobs if not j.get("health_check")]
    if args.machines:
        # A job that isn't on a board yet can't be told apart; keep it.
        jobs = [
            j for j in jobs if not j.get("actual_device") or j["actual_device"] in hosts
        ]
    return sorted(jobs, key=lambda j: j["id"])


def fetch_summaries(api, jobs, logs=True, save=None):
    """Summaries of the jobs; with save, also write everything to that dir."""

    def one(job):
        jid = job["id"]
        tests = api.tests(jid)
        suites = api.suites(jid)
        log = api.log(jid) if logs or save else None
        if save:
            _save(save, job, tests, suites, log)
        return summarize_job(job, tests, suites, log if logs else None)

    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(one, jobs))


def _save(directory, job, tests, suites, log):
    os.makedirs(directory, exist_ok=True)
    base = os.path.join(directory, str(job["id"]))
    for suffix, data in ((".json", job), (".tests.json", tests)):
        with open(base + suffix, "w") as f:
            json.dump(data, f, indent=1)
    with open(base + ".suites.json", "w") as f:
        json.dump(suites, f, indent=1)
    if log is not None:
        with open(base + ".log", "w") as f:
            f.write(log)


def print_report(summaries, as_json=False, save=None):
    if as_json:
        print(json.dumps([s.to_dict() for s in summaries], indent=1))
    else:
        print(format_report(summaries))
    if save:
        with open(os.path.join(save, "report.txt"), "w") as f:
            f.write(format_report(summaries) + "\n")


def cmd_jobs_report(args, system_config, machine_config):
    api = LavaApi.from_config(system_config)
    jobs = select_jobs(api, args, system_config, machine_config)
    if not jobs:
        print("No jobs found.")
        return
    summaries = fetch_summaries(api, jobs, logs=not args.no_logs, save=args.save)
    print_report(summaries, args.json, args.save)
    if any(s.problems() for s in summaries):
        sys.exit(1)
