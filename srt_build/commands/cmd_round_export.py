"""round export - send a round's results to VictoriaMetrics, from the archive.

  srt-build round export                the newest round not exported yet
  srt-build round export 12 --dry-run   print the samples
  srt-build round export 12             send them
  srt-build round export --all          every round not exported yet

The samples are those of `jobs export` (srt_build/metrics.py), built
from the archived files instead of LAVA and Artifactorial, with the
labels round ("12", "t3") and round_kind ("release", "test") on each.
Jobs replaced by a rerun are left out. round.yaml notes when a round
went out ("exported"); a round that did is sent again only with --force
(--all with --force: the whole archive, to refill VictoriaMetrics).
"""

import sys

from ..archive import (
    ArchiveApi,
    archive_path,
    counted_jobs,
    load_round,
    now,
    parse_round,
    round_dir,
    round_ids,
    round_kind,
    save_round,
)
from ..metrics import exportable, job_samples
from ..report import summarize_job
from ..victoria import load_metrics_config, send_or_print
from .cmd_round import add_round_arg


def add_parsers(sub):
    p = sub.add_parser("export", help="send a round's results to VictoriaMetrics")
    add_round_arg(p)
    p.add_argument("--all", action="store_true", help="every round not exported yet")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the samples (VictoriaMetrics' JSON lines), send nothing",
    )
    p.add_argument("--force", action="store_true", help="also rounds sent before")
    p.set_defaults(func=cmd_round_export)


def with_round(samples, rid):
    """samples with the labels round and round_kind. Not "kind":
    srt_job_problems has a label kind (health, failed, ...)."""
    for s in samples:
        s["metric"]["round"] = str(rid)
        s["metric"]["round_kind"] = round_kind(rid)
    return samples


def archived_samples(rdir, jid, rid):
    """The samples of an archived job, with the round labels; None if
    it is no round result (a health check)."""
    a = ArchiveApi(rdir)
    job = a.job(jid)
    if job.get("state") != "Finished" or not exportable(job):
        return None
    tests = a.tests(jid)
    summary = summarize_job(job, tests, a.suites(jid), a.log(jid))
    return with_round(job_samples(job, tests, summary, a.uploads(jid)), rid)


def round_samples(archive, info):
    """(job id, samples) of every job of the round that counts and is
    whole in the archive."""
    rdir = round_dir(archive, info["round"])
    for jid in counted_jobs(info):
        if not ArchiveApi(rdir).complete(jid):
            print(f"job {jid}: not in the archive yet (round report)", file=sys.stderr)
            continue
        samples = archived_samples(rdir, jid, info["round"])
        if samples is not None:
            yield jid, samples


def export_round(archive, info, cfg, dry_run=False):
    """Send (or print) one round; the number of samples and of jobs."""
    total = jobs = 0
    for jid, samples in round_samples(archive, info):
        send_or_print(cfg, f"job {jid}", samples, dry_run)
        total += len(samples)
        jobs += 1
    if not dry_run and jobs:
        info["exported"] = now()
        save_round(archive, info)
    return total, jobs


def unexported(archive):
    """The rounds not exported yet, oldest first."""
    return [r for r in round_ids(archive) if not load_round(archive, r).get("exported")]


def newest_unexported(archive):
    """The round started last of those not exported yet."""
    rids = unexported(archive)
    if not rids:
        return None
    return max(rids, key=lambda r: (str(load_round(archive, r).get("started")), r))


def export_rounds(archive, rids, dry_run=False, force=False, system_config=None):
    cfg = None if dry_run else load_metrics_config(system_config or {})
    verb = "would send" if dry_run else "sent"
    for rid in rids:
        info = load_round(archive, rid)
        if info.get("exported") and not force and not dry_run:
            print(f"round {rid} went out {info['exported']}; --force sends it again")
            continue
        total, jobs = export_round(archive, info, cfg, dry_run)
        what = f"{verb} {total} samples of {jobs} jobs" if jobs else "nothing to export"
        print(f"round {rid}: {what}", file=sys.stderr)


def cmd_round_export(args, system_config, machine_config):
    archive = archive_path(system_config)
    if args.all:
        rids = round_ids(archive) if args.force else unexported(archive)
    elif args.round is not None:
        rids = [parse_round(args.round)]
    else:
        rid = newest_unexported(archive)
        if rid is None:
            print("every round went out", file=sys.stderr)
            return
        rids = [rid]
    export_rounds(archive, rids, args.dry_run, args.force, system_config)
