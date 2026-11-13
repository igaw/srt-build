"""round report and round import - a round's jobs into the archive.

  srt-build round report [N]                fetch what is missing, report
  srt-build round import N --ids 912-965    a round from jobs that ran

`round report` fetches every finished job of the round that the
archive doesn't have whole yet (job, results, suites, log, uploads;
scrubbed of secrets), then reports the round from the archive: the
table of `jobs report`, also in <archive>/N/report.txt. A job that
hasn't finished is shown as such and fetched by the next `round
report`. Exits with 1 if any job has a problem, like `jobs report`.

`round import` is for rounds that ran before `round start` existed:
round.yaml from the jobs' srt.* metadata, then as `round report`.
Importing more ids into a round adds them.
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor

from .. import artifactorial
from ..archive import (
    ArchiveApi,
    archive_path,
    counted_jobs,
    definitions_commit,
    delete_uploads,
    fetch_job,
    is_complete,
    job_entry,
    load_round,
    new_round,
    now,
    parse_round,
    remaining_upload_urls,
    round_dir,
    round_ids,
    save_round,
    test_definitions,
    write_atomic,
)
from ..lava_api import LavaApi
from ..metrics import job_metadata
from ..report import _id_ranges, format_report, parse_id_list, summarize_job
from ..rounds import check_instance, check_new_jobs, lava_instance
from .cmd_round import add_round_arg, pick_round


def add_parsers(sub):
    p = sub.add_parser("report", help="fetch a round into the archive and report it")
    add_round_arg(p)
    add_keep_uploads(p)
    p.set_defaults(func=cmd_round_report)

    p = sub.add_parser("import", help="make a round of jobs that already ran")
    p.add_argument("round", help="the round: 12 (release), t3 (test)")
    p.add_argument("--test", action="store_true", help="a test round (3 means t3)")
    p.add_argument("--notes", help="a line about the round, for round.yaml")
    add_keep_uploads(p)
    p.add_argument(
        "--ids", required=True, metavar="LIST", help="its LAVA jobs, e.g. 912-965"
    )
    p.set_defaults(func=cmd_round_import)


def add_keep_uploads(p):
    p.add_argument(
        "--keep-uploads",
        action="store_true",
        help="don't delete the uploads from Artifactorial once archived",
    )


def fetch_round(api, rdir, info):
    """Fetch the round's finished jobs that aren't whole in the archive.

    Returns {job id: LAVA job} of those that haven't finished.
    """
    todo = [j for j in sorted(info["jobs"]) if not is_complete(rdir, j)]
    if not todo:
        return {}
    with ThreadPoolExecutor(8) as pool:
        jobs = list(pool.map(api.job, todo))

    def one(job):
        missing = fetch_job(api, rdir, job)
        if missing:
            print(
                f"job {job['id']}: uploads not fetched, next time again: "
                + ", ".join(missing),
                file=sys.stderr,
            )

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(one, [j for j in jobs if j.get("state") == "Finished"]))
    return {j["id"]: j for j in jobs if j.get("state") != "Finished"}


def round_summaries(rdir, info, pending=None):
    """JobSummary of every job that counts, from the archive; from LAVA's
    job object (pending) for those that haven't finished."""
    a = ArchiveApi(rdir)
    out = []
    for jid in counted_jobs(info):
        if pending and jid in pending:
            out.append(summarize_job(pending[jid], []))
        elif a.has(jid):
            out.append(
                summarize_job(a.job(jid), a.tests(jid), a.suites(jid), a.log(jid))
            )
        else:
            entry = info["jobs"][jid]
            job = {"id": jid, "actual_device": entry.get("board"), "state": "?"}
            job["description"] = entry.get("test", "")
            out.append(summarize_job(job, []))
    return out


def report_text(info, summaries, rdir):
    lines = [format_report(summaries)]
    reruns = info.get("reruns") or {}
    if reruns:
        lines.append(
            "replaced by a rerun: "
            + ", ".join(f"{old} by {new}" for old, new in sorted(reruns.items()))
        )
    partial = [s.id for s in summaries if s.finished and not is_complete(rdir, s.id)]
    if partial:
        lines.append(f"not whole in the archive yet: jobs {_id_ranges(partial)}")
    return "\n".join(lines)


def report_round(api, system_config, archive, info, keep_uploads=False):
    """Fetch what is missing, write report.txt and round.yaml; the
    summaries. api: LavaApi, or None if LAVA isn't needed. Unless
    keep_uploads, delete the uploads of whole jobs from Artifactorial
    (their copies verified)."""
    rdir = round_dir(archive, info["round"])
    pending = {}
    if any(not is_complete(rdir, j) for j in info["jobs"]):
        api = api or LavaApi.from_config(system_config)
        check_instance(info, system_config, api)
        pending = fetch_round(api, rdir, info)

    if not keep_uploads:
        delete_archived(system_config, rdir, sorted(info["jobs"]))
    summaries = round_summaries(rdir, info, pending)
    a = ArchiveApi(rdir)
    td = info.get("test_definitions") or {}
    if not td.get("url"):
        jobs = [a.job(j) for j in counted_jobs(info) if a.has(j)][:1]
        td = {**(test_definitions(jobs) or {}), **td}
        info["test_definitions"] = td or None
    if not td.get("commit"):
        for jid in counted_jobs(info):
            commit = a.has(jid) and definitions_commit(a.tests(jid))
            if commit:
                info["test_definitions"] = {**td, "commit": commit}
                break
    text = report_text(info, summaries, rdir)
    write_atomic(os.path.join(rdir, "report.txt"), text + "\n")
    if not info.get("reported") and all(
        is_complete(rdir, j) for j in counted_jobs(info)
    ):
        info["reported"] = now()
    save_round(archive, info)
    print(text)
    return summaries


def delete_archived(system_config, rdir, job_ids):
    """Delete the archived uploads from Artifactorial, say what failed."""
    todo = [j for j in job_ids if remaining_upload_urls(rdir, j)]
    if not todo:
        return
    token = artifactorial.upload_token(system_config)
    results = delete_uploads(rdir, todo, token, artifactorial.delete)
    done = [r for r in results if r[2] in ("deleted", "gone")]
    for jid, name, result in results:
        if result not in ("deleted", "gone"):
            print(f"job {jid}: {name}: {result}", file=sys.stderr)
    print(f"{len(done)} uploads deleted from Artifactorial", file=sys.stderr)


def cmd_round_report(args, system_config, machine_config):
    archive, number = pick_round(args, system_config)
    info = load_round(archive, number)
    summaries = report_round(
        None, system_config, archive, info, getattr(args, "keep_uploads", False)
    )
    if any(s.problems() for s in summaries):
        sys.exit(1)


def cmd_round_import(args, system_config, machine_config):
    archive = archive_path(system_config)
    rid = parse_round(args.round, getattr(args, "test", False))
    api = LavaApi.from_config(system_config)
    ids = parse_id_list(args.ids)
    with ThreadPoolExecutor(8) as pool:
        jobs = list(pool.map(api.job, ids))
    checks = [j["id"] for j in jobs if j.get("health_check")]
    if checks:
        print(f"left out, LAVA health checks: {_id_ranges(checks)}", file=sys.stderr)
        jobs = [j for j in jobs if not j.get("health_check")]

    lava = lava_instance(system_config, api)
    check_new_jobs(archive, lava, rid, [j["id"] for j in jobs])
    if rid in round_ids(archive):
        info = load_round(archive, rid)
        check_instance(info, system_config, api)
        for job in jobs:
            info["jobs"].setdefault(job["id"], job_entry(job))
        info["boards"] = sorted(
            set(info.get("boards") or []) | {e["board"] for e in info["jobs"].values()}
        )
        info.pop("reported", None)
    else:
        info = new_round(rid, lava, jobs, imported=now())
    if getattr(args, "notes", None):
        info["notes"] = args.notes
    builds = {str(job_metadata(j).get("srt.build")) for j in jobs} - {"None"}
    if len(builds) > 1:
        print(f"jobs of several srt-build versions: {', '.join(sorted(builds))}")
    save_round(archive, info)
    summaries = report_round(
        api, system_config, archive, info, getattr(args, "keep_uploads", False)
    )
    if any(s.problems() for s in summaries):
        sys.exit(1)
