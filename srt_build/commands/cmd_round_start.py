"""round start and round rerun - submit a round, replace a job of it.

  srt-build round start [--boards bbb,c2d] [--round N] [--test] [--dry-run]
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

`round rerun N JOB` submits JOB's definition again, unchanged (it
carries srt.round), for a lab failure: the new job replaces JOB in
reports and exports; JOB stays in the archive.
"""

import argparse
import os
import subprocess
import sys


from .. import config
from ..archive import (
    RELEASE,
    TEST,
    archive_path,
    load_round,
    new_round,
    next_round,
    parse_round,
    round_ids,
    save_round,
)
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


def add_parsers(sub):
    p = sub.add_parser("start", help="submit a round (in the kernel tree)")
    p.add_argument("--boards", help="these boards (default: config.yml rounds)")
    p.add_argument("--round", help="its number (default: the next)")
    p.add_argument("--test", action="store_true", help="a test round (t1, t2, ...)")
    p.add_argument("--notes", help="a line about the round, for round.yaml")
    p.add_argument(
        "--dry-run", action="store_true", help="render the jobs, submit nothing"
    )
    p.add_argument("--yes", action="store_true", help="don't ask on warnings")
    p.set_defaults(func=cmd_round_start)

    p = sub.add_parser("rerun", help="submit a job of a round again")
    p.add_argument("round", help="the round: 12 (release), t3 (test)")
    p.add_argument("job", type=int, help="the job to replace")
    p.set_defaults(func=cmd_round_rerun)


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


def disk_warnings(system_config):
    free = lava_free_gb(system_config)
    limit = int(system_config.get("lava-disk-min-gb", LAVA_DISK_MIN_GB))
    if free is None:
        return ["the LAVA server's free disk is unknown (ssh failed)"]
    if free < limit:
        return [f"the LAVA server has {free}G free, less than {limit}G"]
    return []


def board_args(board, submission, rid):
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


def cmd_round_start(args, system_config, machine_config, kernel_config):
    archive = archive_path(system_config)
    info = plan(args, system_config, machine_config)
    rid, subs = info["round"], info["submissions"]
    print(f"round {rid} ({info['kind']}) on {info['lava']}: srt-build "
          f"{info['srt_build']}, kernel {info['kernel']}")  # fmt: skip
    print(f"  boards {', '.join(info['boards'])}; per board: " + "; ".join(
        "lava --skip-build " + " ".join(f"--{k} {v}" for k, v in s.items())
        for s in subs
    ))  # fmt: skip
    warnings = checkout_warnings(fetch=not args.dry_run) + disk_warnings(system_config)
    for w in warnings:
        print(f"warning: {w}")
    if args.dry_run:
        for board in info["boards"]:
            for sub in subs:
                dry_run_board(board_args(board, sub, rid), system_config,
                              machine_config, kernel_config)  # fmt: skip
        return
    if warnings and not confirm("submit anyway?", args.yes):
        raise SystemExit("nothing submitted")

    save_round(archive, info)
    for board in info["boards"]:
        for i, sub in enumerate(subs):
            submit_board(board_args(board, sub, rid), info, i, system_config,
                         machine_config, kernel_config)  # fmt: skip
    print_round(info)


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
