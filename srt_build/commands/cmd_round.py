"""Round commands - a test round as one unit (doc/ROUNDS.md).

  srt-build round start [--test] [--dry-run]  submit a round (kernel tree)
  srt-build round status [N] / round wait [N] follow it
  srt-build round rerun N JOB               replace a job of it
  srt-build round compare A B               line up two rounds
  srt-build round import 12 --ids 912-965   backfill a round that ran
  srt-build round report [N]                fetch it into the archive, report
  srt-build round export [N] [--dry-run]    send it to VictoriaMetrics
  srt-build round list                      the rounds in the archive
  srt-build round drop N / round prune      remove a round / old test rounds

A round's results are kept in the round archive (system_config
"round-archive", default ~/.local/share/srt-build/rounds), the master
copy and the only record: there is no database. N defaults to the
round started last; 12 is a release round, t3 a test round (every
`lava` command makes one).
"""

import os
import sys

from ..archive import (
    RELEASE,
    archive_path,
    counted_jobs,
    is_complete,
    load_round,
    newest_round,
    parse_round,
    round_dir,
    round_ids,
)


def add_parser(subparser):
    from . import (
        cmd_round_compare,
        cmd_round_drop,
        cmd_round_export,
        cmd_round_report,
        cmd_round_start,
        cmd_round_status,
    )

    p = subparser.add_parser("round", help="test rounds and the round archive")
    sub = p.add_subparsers(help="round commands", dest="round_cmd", required=True)
    cmd_round_start.add_parsers(sub)
    cmd_round_status.add_parsers(sub)
    cmd_round_report.add_parsers(sub)
    cmd_round_compare.add_parsers(sub)
    cmd_round_export.add_parsers(sub)
    cmd_round_drop.add_parsers(sub)

    q = sub.add_parser("list", help="the rounds in the archive")
    q.add_argument("--test", action="store_true", help="also the test rounds")
    q.set_defaults(func=cmd_round_list)
    return p


def add_round_arg(p):
    p.add_argument(
        "round",
        nargs="?",
        help="the round: 12 (release), t3 (test); default: the one started last",
    )


def pick_round(args, system_config):
    """(archive, round id) of the command."""
    archive = archive_path(system_config)
    rid = getattr(args, "round", None)
    if rid is None:
        rid = newest_round(archive)
        if rid is None:
            raise SystemExit(f"no rounds in {archive}")
    return archive, parse_round(rid)


def confirm(question, yes=False):
    """Ask before deleting; --yes answers for scripts. No terminal, no
    answer: no."""
    if yes:
        return True
    if not sys.stdin.isatty():
        print(f"{question} -- not a terminal, use --yes", file=sys.stderr)
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def fetched_jobs(archive, info):
    rdir = round_dir(archive, info["round"])
    return [j for j in info.get("jobs") or {} if is_complete(rdir, j)]


def _result(archive, number):
    """The last line of the round's report: jobs, health, problems."""
    try:
        with open(os.path.join(round_dir(archive, number), "report.txt")) as f:
            lines = f.read().strip().splitlines()
        return lines[-1] if lines else ""
    except FileNotFoundError:
        return "not reported"


def cmd_round_list(args, system_config, machine_config):
    archive = archive_path(system_config)
    rows = [["round", "started", "kernel", "srt-build", "jobs", "fetched", "exported"]]
    results = []
    kind = None if getattr(args, "test", False) else RELEASE
    for n in round_ids(archive, kind):
        info = load_round(archive, n)
        jobs = counted_jobs(info)
        fetched = set(fetched_jobs(archive, info))
        rows.append(
            [
                str(n),
                str(info.get("started", ""))[:10],
                str(info.get("kernel") or "-"),
                str(info.get("srt_build") or "-")[:12],
                str(len(jobs)),
                str(len(fetched & set(jobs))),
                str(info.get("exported") or "-")[:10],
            ]
        )
        results.append(_result(archive, n))
    if len(rows) == 1:
        print(f"no rounds in {archive}")
        return
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r, result in zip(rows, ["result"] + results):
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)) + "  " + result)
