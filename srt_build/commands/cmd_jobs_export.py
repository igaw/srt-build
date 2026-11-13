"""Jobs export command - send the results of finished jobs to VictoriaMetrics.

  srt-build jobs export                          the newest round not sent yet
  srt-build jobs export --ids 912-965 --dry-run  print these jobs' samples
  srt-build jobs export --since 242              send every job after 242

Each job's results, problems and the histograms of its rt-tests/rtla
uploads become samples at the job's end time (srt_build/metrics.py);
Grafana's rt-tests dashboards show them. Without arguments this is
`round export` of the newest round not exported yet. With --ids,
--since or boards it sends exactly those jobs, nothing is noted: a job
the archive knows gets its round's labels and its archived data, any
other job is read from LAVA and Artifactorial. Unfinished jobs, LAVA
health checks, hack sessions and resubmits with other arguments are
left out (metrics.exportable).

Where to send them: srt_build/victoria.py.
"""

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from ..archive import archive_path, is_complete, round_dir
from ..lava_api import LavaApi
from ..metrics import artifact_urls, exportable, job_samples
from ..report import summarize_job
from ..rounds import jobs_in_rounds, lava_instance
from ..victoria import load_metrics_config, send_or_print
from .cmd_jobs_report import add_selection_args, select_jobs
from .cmd_round_export import archived_samples, export_rounds, newest_unexported
from .cmd_round_export import with_round


def add_parser(subparser):
    p = subparser.add_parser(
        "export", help="send the results of finished jobs to VictoriaMetrics"
    )
    add_selection_args(p)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the samples (VictoriaMetrics' JSON lines), send nothing",
    )
    p.add_argument(
        "--no-artifacts",
        action="store_true",
        help="don't fetch the uploads (no histograms)",
    )
    p.set_defaults(func=cmd_jobs_export)
    return p


def fetch_artifacts(urls, timeout=60):
    """{name: parsed JSON} of the uploads that can still be fetched
    (they stay on artifactorial until deleted: by `round report` once
    archived, or `jobs purge`)."""
    out = {}
    for name, url in urls.items():
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                out[name] = json.load(r)
        except (OSError, ValueError) as exc:
            print(f"  {name}: not fetched ({exc})", file=sys.stderr)
    return out


def collect(api, job, artifacts=True):
    """The samples of one job."""
    jid = job["id"]
    tests = api.tests(jid)
    summary = summarize_job(job, tests, api.suites(jid), api.log(jid))
    arts = fetch_artifacts(artifact_urls(tests)) if artifacts else {}
    return job_samples(job, tests, summary, arts)


def samples_of(api, job, rounds, archive, artifacts=True):
    """A job's samples: from the archive if it has the job whole, else
    from LAVA; with its round's labels if it is in one."""
    rid = rounds.get(job["id"])
    if rid is None:
        return collect(api, job, artifacts)
    rdir = round_dir(archive, rid)
    if is_complete(rdir, job["id"]):
        return archived_samples(rdir, job["id"], rid) or []
    return with_round(collect(api, job, artifacts), rid)


def export_jobs(api, jobs, system_config, dry_run=False, artifacts=True):
    """Send the finished ones of jobs (REST job objects); also `jobs watch
    --export`. Returns the number of samples."""
    cfg = None if dry_run else load_metrics_config(system_config)
    jobs = [j for j in jobs if j.get("state") == "Finished" and exportable(j)]
    if not jobs:
        print("nothing to export", file=sys.stderr)
        return 0
    archive = archive_path(system_config)
    rounds = jobs_in_rounds(
        archive, lava_instance(system_config, api), [j["id"] for j in jobs]
    )

    def one(job):
        return job, samples_of(api, job, rounds, archive, artifacts)

    total = 0
    with ThreadPoolExecutor(8) as pool:
        for job, samples in pool.map(one, jobs):
            send_or_print(cfg, f"job {job['id']}", samples, dry_run)
            total += len(samples)
    verb = "would send" if dry_run else "sent"
    print(f"{verb} {total} samples of {len(jobs)} jobs", file=sys.stderr)
    return total


def cmd_jobs_export(args, system_config, machine_config):
    if not args.dry_run:
        load_metrics_config(system_config)  # fail before fetching anything
    if args.since is None and not args.ids and not args.machines:
        archive = archive_path(system_config)
        rid = newest_unexported(archive)
        if rid is None:
            print("every round went out", file=sys.stderr)
            return
        export_rounds(archive, [rid], args.dry_run, False, system_config)
        return
    api = LavaApi.from_config(system_config)
    jobs = select_jobs(api, args, system_config, machine_config)
    export_jobs(api, jobs, system_config, args.dry_run, not args.no_artifacts)
