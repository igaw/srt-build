"""Jobs dashboard command - write the rt-tests Grafana dashboards.

  srt-build jobs dashboard ~/homelab/lab/plays/files/monitor/dashboards

writes rt-tests.json (the overview: a trend per board and test) and
rt-test-detail.json (one board, flavor and test in depth) into the
directory. They show what `jobs export` sends (srt_build/grafana.py);
homelab provisions the files. --queries also writes every query, one
JSON object per line, to try them against VictoriaMetrics first.
"""

import json
import os

from ..grafana import build_all, queries


def add_parser(subparser):
    p = subparser.add_parser("dashboard", help="write the rt-tests Grafana dashboards")
    p.add_argument("output", help="directory for the dashboard JSON files")
    p.add_argument("--queries", metavar="FILE", help="also write every query")
    p.add_argument(
        "--lava-url",
        help="LAVA's web address for the job links (default: system_config "
        "lava-web, else the REST API's host)",
    )
    p.set_defaults(func=cmd_jobs_dashboard)
    return p


def lava_web_url(system_config):
    url = system_config.get("lava-web")
    if url:
        return url
    from ..lava_api import LavaApi

    return LavaApi.from_config(system_config).base.split("/api/")[0]


def cmd_jobs_dashboard(args, system_config, machine_config):
    if not os.path.isdir(args.output):
        raise SystemExit(f"{args.output}: not a directory")
    dashboards = build_all(args.lava_url or lava_web_url(system_config))
    for name, dashboard in dashboards.items():
        with open(os.path.join(args.output, name), "w", encoding="utf-8") as f:
            json.dump(dashboard, f, indent=2, ensure_ascii=False)
            f.write("\n")
    if args.queries:
        with open(args.queries, "w", encoding="utf-8") as f:
            for dashboard in dashboards.values():
                for q in queries(dashboard):
                    f.write(json.dumps({"dashboard": dashboard["uid"], **q}) + "\n")
