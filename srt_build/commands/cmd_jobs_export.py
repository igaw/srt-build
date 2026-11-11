"""Jobs export command - send the results of finished jobs to VictoriaMetrics.

  srt-build jobs export --since 242 --dry-run     print the samples
  srt-build jobs export --since 242               send them
  srt-build jobs export --ids 108-187 --force     send these again

Each job's results, problems and the histograms of its rt-tests/rtla
uploads become samples at the job's end time (srt_build/metrics.py);
Grafana's rt-tests dashboards show them. A job that went out is noted
in the job database and skipped next time (--force sends it again).
Unfinished jobs, LAVA health checks, hack sessions and resubmits with
other arguments are left out (metrics.exportable).

Where to send them: ~/.config/srt-build/metrics.yml (or the file in
system_config "metrics-config"), not in the repo as it has a password:

  url: http://monitor.lan:8427      # vmauth
  username: srt-build               # may use /api/v1/import
  password: ...
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import yaml

from ..database import get_exported_jobs, mark_exported
from ..lava_api import LavaApi
from ..metrics import artifact_urls, exportable, job_samples, to_jsonl
from ..report import summarize_job
from .cmd_jobs_report import add_selection_args, select_jobs

METRICS_CONFIG = os.path.expanduser("~/.config/srt-build/metrics.yml")


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
        "--force", action="store_true", help="also jobs that were sent before"
    )
    p.add_argument(
        "--no-artifacts",
        action="store_true",
        help="don't fetch the uploads (no histograms)",
    )
    p.set_defaults(func=cmd_jobs_export)
    return p


def load_metrics_config(system_config):
    path = system_config.get("metrics-config", METRICS_CONFIG)
    try:
        with open(os.path.expanduser(path)) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise SystemExit(
            f"no {path}: where to send the samples (see jobs export -h)"
        ) from None
    if not cfg.get("url"):
        raise SystemExit(f"{path}: no url")
    return cfg


def fetch_artifacts(urls, timeout=60):
    """{name: parsed JSON} of the uploads that can still be fetched
    (artifactorial keeps them 90 days)."""
    out = {}
    for name, url in urls.items():
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                out[name] = json.load(r)
        except (OSError, ValueError) as exc:
            print(f"  {name}: not fetched ({exc})", file=sys.stderr)
    return out


def send(cfg, body):
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/api/v1/import",
        data=body.encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if cfg.get("username"):
        cred = f"{cfg['username']}:{cfg.get('password', '')}".encode()
        req.add_header("Authorization", "Basic " + base64.b64encode(cred).decode())
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()


def collect(api, job, artifacts=True):
    """The samples of one job."""
    jid = job["id"]
    tests = api.tests(jid)
    summary = summarize_job(job, tests, api.suites(jid), api.log(jid))
    arts = fetch_artifacts(artifact_urls(tests)) if artifacts else {}
    return job_samples(job, tests, summary, arts)


def export_jobs(api, jobs, system_config, dry_run=False, force=False, artifacts=True):
    """Send the finished ones of jobs (REST job objects); also `jobs watch
    --export`. Returns the number of samples."""
    cfg = None if dry_run else load_metrics_config(system_config)
    jobs = [j for j in jobs if j.get("state") == "Finished" and exportable(j)]
    if not force:
        done = get_exported_jobs(system_config)
        jobs = [j for j in jobs if j["id"] not in done]
    if not jobs:
        print("nothing to export", file=sys.stderr)
        return 0

    total = 0
    with ThreadPoolExecutor(8) as pool:
        for job, samples in pool.map(lambda j: (j, collect(api, j, artifacts)), jobs):
            if dry_run:
                sys.stdout.write(to_jsonl(samples))
            else:
                try:
                    send(cfg, to_jsonl(samples))
                except (OSError, urllib.error.HTTPError) as exc:
                    raise SystemExit(f"job {job['id']}: sending failed: {exc}") from exc
                mark_exported(job["id"], len(samples), system_config)
            total += len(samples)
    verb = "would send" if dry_run else "sent"
    print(f"{verb} {total} samples of {len(jobs)} jobs", file=sys.stderr)
    return total


def cmd_jobs_export(args, system_config, machine_config):
    api = LavaApi.from_config(system_config)
    if not args.dry_run:
        load_metrics_config(system_config)  # fail before fetching anything
    jobs = select_jobs(api, args, system_config, machine_config)
    export_jobs(
        api, jobs, system_config, args.dry_run, args.force, not args.no_artifacts
    )
