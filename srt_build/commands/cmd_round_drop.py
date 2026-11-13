"""round drop and round prune - remove rounds and everything of them.

  srt-build round drop 12 [--metrics] [--dry-run] [--yes]
  srt-build round prune [--metrics] [--dry-run] [--yes]

Removing a round removes its archive directory, the uploads it still
has on Artifactorial and, with
--metrics, its series in VictoriaMetrics ({round="12",
round_kind="release"}). It lists what will go and asks first.

Release rounds go only by `round drop`. Test rounds expire: `round
prune` drops those started more than config.yml rounds:
test-retention-days (30) ago. The jobs stay in LAVA (deleting them
there is for LAVA's admin).
"""

import shutil
import sys
from datetime import datetime, timedelta, timezone

from .. import artifactorial, config
from ..archive import (
    TEST,
    ArchiveApi,
    archive_path,
    load_round,
    parse_round,
    remaining_upload_urls,
    round_dir,
    round_ids,
    round_kind,
)
from ..metrics import artifact_urls
from ..victoria import delete_series, load_metrics_config
from .cmd_round import confirm

DEFAULT_TEST_RETENTION_DAYS = 30


def add_parsers(sub):
    p = sub.add_parser("drop", help="remove a round: archive, uploads, series")
    p.add_argument("round", help="the round: 12 (release), t3 (test)")
    _common(p)
    p.set_defaults(func=cmd_round_drop)
    p = sub.add_parser("prune", help="drop the test rounds that expired")
    _common(p)
    p.set_defaults(func=cmd_round_prune)


def _common(p):
    p.add_argument(
        "--metrics", action="store_true", help="also its series in VictoriaMetrics"
    )
    p.add_argument("--dry-run", action="store_true", help="list, delete nothing")
    p.add_argument("--yes", action="store_true", help="don't ask")


def series_selector(rid):
    return f'{{round="{rid}", round_kind="{round_kind(rid)}"}}'


def upload_urls(system_config, archive, info, api=None):
    """The round's uploads that may still be on Artifactorial: those not
    deleted of archived jobs, from LAVA those of jobs not archived."""
    rdir = round_dir(archive, info["round"])
    a = ArchiveApi(rdir)
    urls = []
    for jid in sorted(info.get("jobs") or {}):
        if a.has(jid):
            urls += remaining_upload_urls(rdir, jid)
            continue
        try:
            if api is None:
                from ..lava_api import LavaApi

                api = LavaApi.from_config(system_config)
            urls += list(artifact_urls(api.tests(jid)).values())
        except (OSError, KeyError) as exc:
            print(f"job {jid}: uploads unknown ({exc})", file=sys.stderr)
    return urls


def expired_test_rounds(archive, days, now=None):
    now = now or datetime.now(timezone.utc)
    out = []
    for rid in round_ids(archive, TEST):
        started = str(load_round(archive, rid).get("started") or "")
        try:
            when = datetime.fromisoformat(started.replace("Z", "+00:00"))
        except ValueError:
            continue
        if now - when > timedelta(days=days):
            out.append(rid)
    return out


def drop_rounds(system_config, archive, rids, args, api=None):
    """List what goes, ask, remove it. Returns whether it did."""
    plans = []
    for rid in rids:
        info = load_round(archive, rid)
        urls = upload_urls(system_config, archive, info, api)
        plans.append((rid, urls))
        print(f"round {rid}: {round_dir(archive, rid)} ({len(info['jobs'])} jobs)")
        print(f"  {len(urls)} uploads on Artifactorial")
        if args.metrics:
            print(f"  VictoriaMetrics series {series_selector(rid)}")
    if args.dry_run or not plans:
        return False
    if not confirm(f"remove {len(plans)} round(s)?", args.yes):
        raise SystemExit("nothing removed")

    cfg = load_metrics_config(system_config) if args.metrics else None
    token = None
    for rid, urls in plans:
        if urls:
            token = token or artifactorial.upload_token(system_config)
            results = artifactorial.delete_all(urls, token, artifactorial.delete)
            failed = {u: r for u, r in results.items() if r.startswith("failed")}
            for url, result in failed.items():
                print(
                    f"  {artifactorial.artifact_path(url)}: {result}", file=sys.stderr
                )
            print(f"round {rid}: {len(urls) - len(failed)} uploads deleted")
        if cfg:
            delete_series(cfg, series_selector(rid))
            print(f"round {rid}: series {series_selector(rid)} deleted")
        shutil.rmtree(round_dir(archive, rid))
        print(f"round {rid}: removed")
    return True


def cmd_round_drop(args, system_config, machine_config):
    archive = archive_path(system_config)
    rid = parse_round(args.round)
    if rid not in round_ids(archive):
        raise SystemExit(f"no round {rid} in {archive}")
    drop_rounds(system_config, archive, [rid], args)


def cmd_round_prune(args, system_config, machine_config):
    archive = archive_path(system_config)
    days = int(
        (config.rounds or {}).get("test-retention-days", DEFAULT_TEST_RETENTION_DAYS)
    )
    rids = expired_test_rounds(archive, days)
    if not rids:
        print(f"no test round older than {days} days")
        return
    drop_rounds(system_config, archive, rids, args)
