"""Read-only client for LAVA's REST API (api/v0.2).

The report and watch commands read jobs, results and logs from here
instead of lavacli: one HTTP request per page, and no lavacli install
needed just to look at results.

The server comes from system_config["lava-api"] if set, otherwise from
the lavacli identity (~/.config/lavacli.yaml, identity "default" or
system_config["lava-identity"]): http://host:port/RPC2 becomes
http://host:port/api/v0.2/.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import yaml

LAVACLI_CONFIG = os.path.expanduser("~/.config/lavacli.yaml")


def api_from_lavacli(path=LAVACLI_CONFIG, identity="default"):
    """Return (api_url, token) derived from a lavacli identity."""
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    ident = cfg.get(identity)
    if not ident or "uri" not in ident:
        raise KeyError(f"no lavacli identity {identity!r} with a uri in {path}")
    uri = urllib.parse.urlsplit(ident["uri"])
    api = urllib.parse.urlunsplit((uri.scheme, uri.netloc, "/api/v0.2/", "", ""))
    return api, ident.get("token")


class LavaApi:
    def __init__(self, base, token=None, timeout=120):
        self.base = base.rstrip("/") + "/"
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_config(cls, system_config):
        base = system_config.get("lava-api")
        token = system_config.get("lava-token")
        if not base:
            identity = system_config.get("lava-identity", "default")
            base, ident_token = api_from_lavacli(identity=identity)
            token = token or ident_token
        return cls(base, token)

    def _open(self, url):
        if not url.startswith("http"):
            url = self.base + url
        req = urllib.request.Request(url)
        if self.token:
            req.add_header("Authorization", f"Token {self.token}")
        return urllib.request.urlopen(req, timeout=self.timeout)

    def get_json(self, url):
        with self._open(url) as r:
            return json.load(r)

    def get_all(self, url):
        """All results of a paginated list endpoint."""
        out = []
        while url:
            page = self.get_json(url)
            out += page["results"]
            url = page.get("next")
        return out

    def job(self, job_id):
        return self.get_json(f"jobs/{job_id}/")

    def tests(self, job_id):
        return self.get_all(f"jobs/{job_id}/tests/?limit=500")

    def suites(self, job_id):
        return self.get_all(f"jobs/{job_id}/suites/?limit=100")

    def log(self, job_id):
        """The job log as LAVA stores it: one YAML/JSON entry per line.

        Empty for a job that hasn't started yet (LAVA answers 404).
        """
        try:
            with self._open(f"jobs/{job_id}/logs/") as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return ""
            raise

    def jobs_after(self, job_id):
        """All jobs with an id greater than job_id, oldest first."""
        return self.get_all(f"jobs/?id__gt={int(job_id)}&ordering=id&limit=200")
