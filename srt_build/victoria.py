"""VictoriaMetrics: where the samples go, sending and deleting them.

Where to send them: ~/.config/srt-build/metrics.yml (or the file in
system_config "metrics-config"), not in the repo as it has a password:

  url: http://monitor.lan:8427      # vmauth
  username: srt-build               # may use /api/v1/import
  password: ...
"""

import base64
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

from .metrics import to_jsonl

METRICS_CONFIG = os.path.expanduser("~/.config/srt-build/metrics.yml")


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


def delete_series(cfg, match, opener=None):
    """Delete the series matching match (a series selector) in
    VictoriaMetrics: /api/v1/admin/tsdb/delete_series, through vmauth
    like send()."""
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/api/v1/admin/tsdb/delete_series",
        data=urllib.parse.urlencode({"match[]": match}).encode(),
        method="POST",
    )
    if cfg.get("username"):
        cred = f"{cfg['username']}:{cfg.get('password', '')}".encode()
        req.add_header("Authorization", "Basic " + base64.b64encode(cred).decode())
    with (opener or urllib.request.urlopen)(req, timeout=60) as r:
        r.read()


def send_or_print(cfg, what, samples, dry_run):
    """Send samples (cfg from load_metrics_config), or print them."""
    if dry_run:
        sys.stdout.write(to_jsonl(samples))
        return
    try:
        send(cfg, to_jsonl(samples))
    except (OSError, urllib.error.HTTPError) as exc:
        raise SystemExit(f"{what}: sending failed: {exc}") from exc
