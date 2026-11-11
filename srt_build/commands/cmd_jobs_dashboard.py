"""Jobs dashboard command - write the rt-tests Grafana dashboard.

  srt-build jobs dashboard ~/homelab/lab/plays/files/monitor/dashboards/rt-tests.json

The dashboard shows what `jobs export` sends (srt_build/grafana.py);
homelab provisions the file. --queries also writes every query, one JSON
object per line, to try them against VictoriaMetrics first.
"""

import json

from ..grafana import build, queries


def add_parser(subparser):
    p = subparser.add_parser("dashboard", help="write the rt-tests Grafana dashboard")
    p.add_argument("output", help="the dashboard JSON file")
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
    dashboard = build(args.lava_url or lava_web_url(system_config))
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if args.queries:
        with open(args.queries, "w", encoding="utf-8") as f:
            for q in queries(dashboard):
                f.write(json.dumps(q) + "\n")
