"""round start and round rerun - submit a round, replace a job of it.

  srt-build round start [--boards bbb,c2d] [--round N] [--test]
                        [--skip-build] [--dry-run]
  srt-build round rerun 13 961

`round start` runs in the kernel tree, like `lava`: one `lava <board>
--skip-build` per board and entry of config.yml rounds: submissions,
through lava's own code, with the round in each job's metadata
(srt.round). Before submitting it prints what it submits (round,
srt-build, kernel, boards) and warns, asking, when the srt-build
checkout has local changes, is behind or ahead of its upstream, or the
LAVA server's disk is low. round.yaml is written before the first job
and after each board. --dry-run renders every job and submits nothing.
--test makes a test round (t1, t2, ...), as a plain `lava` command does.
It first builds and installs, per board, every flavor the submissions
use, each once, all before the first job: a failed build stops with
nothing submitted and no round in the archive. --skip-build submits
with the kernels installed already, as lava --skip-build does.

`round rerun N JOB` submits JOB's definition again, unchanged (it
carries srt.round), for a lab failure: the new job replaces JOB in
reports and exports; JOB stays in the archive.

`round repeat N` submits the jobs of round N again as a new round (the
next number; --test: the next test round), their definitions unchanged
but srt.round: the same kernels (those N installed, by URL), boards and
tests. It needs no kernel tree, only LAVA: to run a release's round
again, e.g. overnight, from anywhere the lavacli identity works.

`--count K` (start and repeat) submits K rounds in one go, the next K
numbers, each a round of its own with `batch: <first>` in round.yaml.
LAVA runs a board's jobs by priority, then in the order submitted, so
the rounds run back to back, unattended; `round wait --batch` follows
them. A batch's jobs are priority low (--priority: low, medium, high
or 0-100), so other people's jobs go first. The disk check counts
lava-round-gb for every round after the first.
"""

import argparse
import os
import subprocess
import sys

import yaml


from .. import config
from ..archive import (
    RELEASE,
    TEST,
    archive_path,
    counted_jobs,
    load_round,
    new_round,
    next_round,
    parse_round,
    round_ids,
    round_kind,
    save_round,
)
from .. import helpers
from ..helpers import Context, srt_build_version
from ..lava_api import LavaApi, rpc_from_lavacli
from ..rounds import (
    add_jobs,
    check_instance,
    check_new_jobs,
    kernel_describe,
    lava_instance,
    print_round,
    recording_submit,
)
from .cmd_round import confirm

LAVA_DISK_MIN_GB = 10
# What a round leaves on the LAVA server: job logs (round 19, 54 jobs:
# 20 MB), Artifactorial uploads until `round report` deletes them, the
# database; a running job's 0.7-0.9 GB in the dispatcher's tmp is freed
# when it ends and lava-disk-min-gb covers it.
LAVA_ROUND_GB = 1
PRIORITIES = ("low", "medium", "high")


def add_parsers(sub):
    p = sub.add_parser("start", help="submit a round (in the kernel tree)")
    p.add_argument("--boards", help="these boards (default: config.yml rounds)")
    p.add_argument("--round", help="its number (default: the next)")
    p.add_argument("--test", action="store_true", help="a test round (t1, t2, ...)")
    p.add_argument("--notes", help="a line about the round, for round.yaml")
    add_batch_args(p)
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="don't build, submit with the kernels installed already",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="render the jobs, submit nothing"
    )
    p.add_argument("--yes", action="store_true", help="don't ask on warnings")
    p.set_defaults(func=cmd_round_start)

    p = sub.add_parser("repeat", help="submit the jobs of a round again, a new round")
    p.add_argument("round", help="the round to repeat: 12 (release), t3 (test)")
    p.add_argument("--test", action="store_true", help="as a test round")
    p.add_argument("--notes", help="a line about the round (default: repeat of N)")
    p.add_argument(
        "--boards", help="only the jobs of these boards, e.g. rpi3-32,rpi3-64"
    )
    p.add_argument(
        "--tests", help="only these tests, e.g. stress-ng-io,stress-ng-scheduler"
    )
    add_batch_args(p)
    p.add_argument(
        "--dry-run", action="store_true", help="list the jobs, submit nothing"
    )
    p.add_argument("--yes", action="store_true", help="don't ask on warnings")
    p.set_defaults(func=cmd_round_repeat)

    p = sub.add_parser("rerun", help="submit a job of a round again")
    p.add_argument("round", help="the round: 12 (release), t3 (test)")
    p.add_argument("job", type=int, help="the job to replace")
    p.set_defaults(func=cmd_round_rerun)


def add_batch_args(p):
    p.add_argument(
        "--count",
        type=int,
        default=1,
        help="this many rounds in one go, back to back (a batch)",
    )
    p.add_argument(
        "--priority",
        help="the jobs' LAVA priority: low, medium, high or 0-100 "
        "(default: low for a batch, else medium)",
    )


def parse_priority(value):
    """LAVA's job priority: "low", "medium", "high" or 0-100; None."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in PRIORITIES:
        return s
    if s.isdigit() and int(s) <= 100:
        return int(s)
    raise SystemExit(f"bad priority {value!r}: low, medium, high or 0-100")


def batch_of(args):
    """(count, priority) of the command: a batch is low unless told."""
    count = getattr(args, "count", None)
    count = 1 if count is None else count
    if count < 1:
        raise SystemExit("--count: 1 or more rounds")
    priority = parse_priority(getattr(args, "priority", None))
    if priority is None and count > 1:
        priority = "low"
    return count, priority


def following(rid, count):
    """rid and the count - 1 round ids after it: 20, 21, 22; t3, t4."""
    prefix = "t" if round_kind(rid) == TEST else ""
    n = int(str(rid).lstrip("t"))
    return [f"{prefix}{n + i}" for i in range(count)]


def batch_line(rids, priority):
    """What the header says about a batch and the priority."""
    out = []
    if len(rids) > 1:
        out.append(f"  {len(rids)} rounds, one after another: {', '.join(rids)} "
                   f"(batch {rids[0]})")  # fmt: skip
    if priority is not None:
        out.append(f"  priority {priority}")
    return out


def _git(repo, *args, timeout=60):
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def checkout_warnings(repo=None, fetch=True):
    """What is wrong with the srt-build checkout that submits: local
    changes, commits not pushed, commits not pulled (after a fetch)."""
    repo = repo or os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    out = []
    try:
        if _git(repo, "status", "--porcelain").stdout.strip():
            out.append("the srt-build checkout has local changes")
        if fetch and _git(repo, "fetch", "--quiet", timeout=30).returncode:
            out.append("srt-build's upstream could not be fetched")
        for spec, what in (
            ("HEAD..@{u}", "behind its upstream (not pulled)"),
            ("@{u}..HEAD", "ahead of its upstream (not pushed)"),
        ):
            r = _git(repo, "rev-list", "--count", spec)
            if r.returncode:
                out.append("the srt-build checkout has no upstream")
                break
            if int(r.stdout.strip() or 0):
                out.append(f"srt-build is {r.stdout.strip()} commits {what}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        out.append(f"git failed: {exc}")
    return out


def lava_free_gb(system_config):
    """Free GB under /var/lib/lava on the LAVA server, None if it can't
    be asked (ssh as the contrib scripts do)."""
    host = system_config.get("lava-ssh") or f"root@{lava_instance(system_config)}"
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host,
             "df", "-BG", "--output=avail", "/var/lib/lava"],
            capture_output=True, text=True, timeout=30,
        )  # fmt: skip
        return int(r.stdout.split()[-1].rstrip("G")) if r.returncode == 0 else None
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def disk_warnings(system_config, count=1):
    """The minimum, and lava-round-gb for each round after the first."""
    free = lava_free_gb(system_config)
    limit = int(system_config.get("lava-disk-min-gb", LAVA_DISK_MIN_GB))
    per = int(system_config.get("lava-round-gb", LAVA_ROUND_GB))
    need = limit + (count - 1) * per
    if free is None:
        return ["the LAVA server's free disk is unknown (ssh failed)"]
    if free < need and count > 1:
        return [f"the LAVA server has {free}G free, less than the {need}G "
                f"{count} rounds need ({limit}G and {per}G per round after "
                f"the first)"]  # fmt: skip
    if free < need:
        return [f"the LAVA server has {free}G free, less than {limit}G"]
    return []


def board_args(board, submission, rid, priority=None):
    """lava's arguments for one board and entry of submissions."""
    flavors = submission.get("flavors")
    if isinstance(flavors, list):
        flavors = ",".join(flavors)
    return argparse.Namespace(
        machine=board,
        skip_build=True,
        mods=False,
        duration=submission.get("duration"),
        config_base="",
        tests=submission.get("tests"),
        flavors=flavors,
        testsuites=submission.get("testsuites", "smoke"),
        split=bool(submission.get("split", False)),
        list_tests=False,
        show_jobs=False,
        builddir=None,
        append="",
        debug=False,
        round=rid,
        priority=priority,
    )


def plan(args, system_config, machine_config):
    """round.yaml of the round to start, before any job."""
    archive = archive_path(system_config)
    kind = TEST if args.test else RELEASE
    rid = (
        parse_round(args.round, args.test) if args.round else next_round(archive, kind)
    )
    if rid in round_ids(archive):
        raise SystemExit(f"round {rid} exists already")
    cfg = config.rounds or {}
    boards = args.boards.split(",") if args.boards else list(cfg.get("boards") or [])
    unknown = [b for b in boards if b not in machine_config]
    if not boards or unknown:
        raise SystemExit(f"boards: none or unknown: {', '.join(unknown)}")
    info = new_round(
        rid,
        lava_instance(system_config),
        srt_build=srt_build_version(),
        kernel=kernel_describe(),
    )
    info.update(
        boards=boards,
        submissions=list(cfg.get("submissions") or [{}]),
        notes=args.notes,
    )
    return info


def round_like(info, rid):
    """A new round.yaml rid like info (a batch's next round), no jobs."""
    keys = ("srt_build", "test_definitions", "kernel", "notes", "repeats",
            "boards", "submissions", "batch", "priority")  # fmt: skip
    new = new_round(rid, info["lava"], **{k: info.get(k) for k in keys})
    new["jobs"] = {}
    return new


def check_free(archive, rids):
    taken = [r for r in rids if r in round_ids(archive)]
    if taken:
        raise SystemExit(f"round {', '.join(taken)} exists already")


def each_round(archive, info, rids):
    """info, then a round like it for each of the other rids, each in
    the archive before its first job."""
    for n, rid in enumerate(rids):
        if n:
            check_free(archive, [rid])
            info = round_like(info, rid)
        save_round(archive, info)
        yield info
        print_round(info)


def submit_anyway(warnings, yes):
    for w in warnings:
        print(f"warning: {w}")
    if warnings and not confirm("submit anyway?", yes):
        raise SystemExit("nothing submitted")


def start_plan(args, system_config, machine_config):
    """(round.yaml of the first round, its batch's round ids, priority)."""
    count, priority = batch_of(args)
    if count > 1 and args.round:
        raise SystemExit("--count takes the next round numbers, not --round")
    info = plan(args, system_config, machine_config)
    rids = following(info["round"], count)
    check_free(archive_path(system_config), rids)
    info.update(batch=rids[0] if count > 1 else None, priority=priority)
    return info, rids, priority


def submit_board(ctx_args, info, i, system_config, machine_config, kernel_config):
    """Submit one entry of submissions on one board, add its jobs."""
    from .cmd_lava import cmd_lava

    ctx = Context(ctx_args, machine_config, system_config)
    entries = {}
    ctx.submit = recording_submit(entries)
    ids = cmd_lava(ctx, system_config, kernel_config)
    add_jobs(system_config, info, ids, entries, ctx_args.machine, submission=i)


def dry_run_board(ctx_args, system_config, machine_config, kernel_config):
    from .cmd_lava import cmd_lava

    ctx = Context(ctx_args, machine_config, system_config)
    entries = []
    ctx.submit = recording_submit(entries, True)
    cmd_lava(ctx, system_config, kernel_config)
    for e in entries:
        print(f"  would submit: {e['board']} {e['flavor']} {e['test']}")


def submission_command(sub):
    """The lava command of an entry of submissions, as typed."""
    words = ["lava --skip-build"]
    for k, v in sub.items():
        if isinstance(v, list):
            v = ",".join(map(str, v))
        words.append(f"--{k}" if v is True else f"--{k} {v}")
    return " ".join(words)


def build_board(board, subs, rid, system_config, machine_config, kernel_config):
    """Build and install every flavor of the board's submissions, once."""
    from .cmd_lava import cmd_lava

    print(f"{board}: building")
    built = set()
    for sub in subs:
        ctx_args = board_args(board, sub, rid)
        ctx_args.skip_build = False
        ctx_args.built = built
        ctx = Context(ctx_args, machine_config, system_config)
        ctx.submit = recording_submit([], True)
        cmd_lava(ctx, system_config, kernel_config)
    print(f"{board}: built {', '.join(sorted(built)) or 'nothing'}")


def dry_run(info, build, system_config, machine_config, kernel_config,
            count=1, priority=None):  # fmt: skip
    """Render every job of the round, build and submit nothing."""
    if build:
        print("  builds first (not in a dry run): every flavor per board")
    else:
        print("  builds nothing: the kernels installed already")
    if count > 1:
        print(f"  each of the {count} rounds:")
    for board in info["boards"]:
        for sub in info["submissions"]:
            dry_run_board(board_args(board, sub, info["round"], priority),
                          system_config, machine_config, kernel_config)  # fmt: skip


def cmd_round_start(args, system_config, machine_config, kernel_config):
    archive = archive_path(system_config)
    info, rids, priority = start_plan(args, system_config, machine_config)
    rid, subs, count = info["round"], info["submissions"], len(rids)
    print(f"round {rid} ({info['kind']}) on {info['lava']}: srt-build "
          f"{info['srt_build']}, kernel {info['kernel']}")  # fmt: skip
    for line in batch_line(rids, priority):
        print(line)
    build = not getattr(args, "skip_build", False)
    print(f"  boards {', '.join(info['boards'])}")
    print("  per board: " + ("build and install every flavor, then " if build
                             else "the installed kernels, ")
          + "; ".join(submission_command(s) for s in subs))  # fmt: skip
    warnings = checkout_warnings(fetch=not args.dry_run) + disk_warnings(
        system_config, count
    )
    if args.dry_run:
        for w in warnings:
            print(f"warning: {w}")
        dry_run(info, build, system_config, machine_config, kernel_config,
                count, priority)  # fmt: skip
        return
    submit_anyway(warnings, args.yes)
    helpers.ensure_lavacli_available()
    if build:
        for board in info["boards"]:
            build_board(board, subs, rid, system_config, machine_config,
                        kernel_config)  # fmt: skip

    for one in each_round(archive, info, rids):
        for board in one["boards"]:
            for i, sub in enumerate(subs):
                submit_board(board_args(board, sub, one["round"], priority),
                             one, i, system_config, machine_config,
                             kernel_config)  # fmt: skip


def cmd_round_rerun(args, system_config, machine_config):
    archive = archive_path(system_config)
    rid = parse_round(args.round)
    info = load_round(archive, rid)
    if args.job not in info["jobs"]:
        raise SystemExit(f"job {args.job} is not in round {rid}")
    if args.job in info["reruns"]:
        raise SystemExit(f"job {args.job} was replaced by {info['reruns'][args.job]}")
    api = LavaApi.from_config(system_config)
    check_instance(info, system_config, api)
    definition = api.job(args.job)["definition"]
    rpc = rpc_from_lavacli(identity=system_config.get("lava-identity", "default"))
    new = rpc.scheduler.jobs.submit(definition)
    new = int(new[0] if isinstance(new, list) else new)
    check_new_jobs(archive, info["lava"], rid, [new], own=info["jobs"])
    info["jobs"][new] = dict(info["jobs"][args.job])
    info["reruns"][args.job] = new
    info.pop("reported", None)
    save_round(archive, info)
    print(f"round {rid}: job {args.job} rerun as {new}", file=sys.stderr)


def with_round(definition, rid, priority=None):
    """The job definition with srt.round rid (and priority), else
    unchanged."""
    job = yaml.safe_load(definition)
    job.setdefault("metadata", {})["srt.round"] = str(rid)
    if priority is not None:
        job["priority"] = priority
    return yaml.safe_dump(job, sort_keys=False, default_flow_style=False)


def repeat_dry_run(src, jobs, count):
    if count > 1:
        print(f"  each of the {count} rounds:")
    for j in jobs:
        e = src["jobs"][j]
        print(f"  would submit again: {j}  {e['board']}  {e['flavor']}  {e['test']}")


def _names(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def selected_jobs(src, boards=None, tests=None):
    """The counted jobs of src on these boards and of these tests (all
    if not given); an unknown board or test stops."""
    boards, tests = _names(boards), _names(tests)
    jobs = counted_jobs(src)
    for what, wanted, key in (("board", boards, "board"), ("test", tests, "test")):
        have = {src["jobs"][j][key] for j in jobs}
        unknown = [w for w in wanted if w not in have]
        if unknown:
            raise SystemExit(
                f"round {src['round']} has no {what} {', '.join(unknown)} "
                f"(it has: {', '.join(sorted(have))})"
            )
    jobs = [
        j
        for j in jobs
        if (not boards or src["jobs"][j]["board"] in boards)
        and (not tests or src["jobs"][j]["test"] in tests)
    ]
    if not jobs:
        raise SystemExit(f"round {src['round']} has no such jobs")
    return jobs


def repeat_notes(rid, boards=None, tests=None):
    """The default notes of a repeat: what it repeats, and of it."""
    only = ", ".join(_names(tests) + _names(boards))
    return f"repeat of {rid}" + (f" ({only})" if only else "")


def cmd_round_repeat(args, system_config, machine_config):
    archive = archive_path(system_config)
    count, priority = batch_of(args)
    src = load_round(archive, parse_round(args.round))
    api = LavaApi.from_config(system_config)
    check_instance(src, system_config, api)
    boards, tests = getattr(args, "boards", None), getattr(args, "tests", None)
    jobs = selected_jobs(src, boards, tests)
    kind = TEST if args.test else RELEASE
    rids = following(next_round(archive, kind), count)
    check_free(archive, rids)
    info = new_round(
        rids[0],
        src["lava"],
        srt_build=src.get("srt_build"),
        kernel=src.get("kernel"),
        test_definitions=src.get("test_definitions"),
    )
    info.update(
        boards=sorted({src["jobs"][j]["board"] for j in jobs}),
        submissions=list(src.get("submissions") or []),
        repeats=src["round"],
        notes=args.notes or repeat_notes(src["round"], boards, tests),
        batch=rids[0] if count > 1 else None,
        priority=priority,
    )
    print(f"round {rids[0]} ({info['kind']}) on {info['lava']}: repeats round "
          f"{src['round']}, kernel {info['kernel']}, {len(jobs)} jobs")  # fmt: skip
    for line in batch_line(rids, priority):
        print(line)
    if args.dry_run:
        repeat_dry_run(src, jobs, count)
        return
    submit_anyway(disk_warnings(system_config, count), args.yes)
    definitions = {j: api.job(j)["definition"] for j in jobs}
    rpc = rpc_from_lavacli(identity=system_config.get("lava-identity", "default"))
    for one in each_round(archive, info, rids):
        rid = one["round"]
        for j in jobs:
            new = rpc.scheduler.jobs.submit(with_round(definitions[j], rid, priority))
            new = int(new[0] if isinstance(new, list) else new)
            check_new_jobs(archive, one["lava"], rid, [new], own=one["jobs"])
            one["jobs"][new] = dict(src["jobs"][j])
            save_round(archive, one)
