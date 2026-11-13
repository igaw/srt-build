"""Jobs purge command - delete what jobs outside the rounds left behind.

  srt-build jobs purge --ids 755-777 --dry-run     list it
  srt-build jobs purge --ids 755-777 --metrics     delete it

Hack sessions and jobs submitted by hand aren't rounds and never go
into the archive, but their uploads stay on Artifactorial until
deleted. This deletes them (found through the jobs' LAVA test results)
and, with --metrics, their series in VictoriaMetrics ({job="<id>"}).
It lists what will go and asks first (--yes for scripts). Jobs of an
archived round are refused: `round drop` removes those. The jobs
themselves stay in LAVA (deleting them there is for LAVA's admin).
"""

import sys
from concurrent.futures import ThreadPoolExecutor

from .. import artifactorial
from ..archive import archive_path
from ..lava_api import LavaApi
from ..metrics import artifact_urls
from ..report import parse_id_list
from ..victoria import delete_series, load_metrics_config
from ..rounds import jobs_in_rounds, lava_instance
from .cmd_round import confirm


def add_parser(subparser):
    p = subparser.add_parser(
        "purge", help="delete the uploads (and series) of jobs outside rounds"
    )
    p.add_argument("--ids", required=True, metavar="LIST", help="e.g. 755-777")
    p.add_argument(
        "--metrics", action="store_true", help="also their series in VictoriaMetrics"
    )
    p.add_argument("--dry-run", action="store_true", help="list, delete nothing")
    p.add_argument("--yes", action="store_true", help="don't ask")
    p.set_defaults(func=cmd_jobs_purge)
    return p


def cmd_jobs_purge(args, system_config, machine_config):
    ids = parse_id_list(args.ids)
    api = LavaApi.from_config(system_config)
    archive = archive_path(system_config)
    lava = lava_instance(system_config, api)
    taken = jobs_in_rounds(archive, lava, ids)
    if taken:
        listed = ", ".join(f"{j} (round {r})" for j, r in sorted(taken.items())[:10])
        raise SystemExit(f"jobs of a round, use round drop: {listed}")

    with ThreadPoolExecutor(8) as pool:
        found = list(pool.map(lambda j: artifact_urls(api.tests(j)), ids))
    urls = dict(zip(ids, found, strict=True))
    total = sum(len(u) for u in urls.values())
    for jid in ids:
        line = f"job {jid}: {len(urls[jid])} uploads on Artifactorial"
        if args.metrics:
            line += f', VictoriaMetrics series {{job="{jid}"}}'
        print(line)
    if args.dry_run:
        return
    if not confirm(f"delete {total} uploads of {len(ids)} jobs?", args.yes):
        raise SystemExit("nothing deleted")

    cfg = load_metrics_config(system_config) if args.metrics else None
    token = artifactorial.upload_token(system_config) if total else None
    failed = purge(ids, urls, token, cfg)
    print(f"{total - failed} uploads deleted", file=sys.stderr)
    if failed:
        sys.exit(1)


def purge(ids, urls, token, cfg):
    """Delete the jobs' uploads and, with cfg, series; the failures."""
    failed = 0
    for jid in ids:
        results = artifactorial.delete_all(
            list(urls[jid].values()), token, artifactorial.delete
        )
        for url, result in results.items():
            if result.startswith("failed"):
                failed += 1
                print(f"job {jid}: {artifactorial.artifact_path(url)}: {result}")
        if cfg:
            delete_series(cfg, f'{{job="{jid}"}}')
    return failed
