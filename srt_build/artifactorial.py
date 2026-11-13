"""Deleting uploads on Artifactorial.

The rt-tests and rtla JSON files the jobs upload stay on Artifactorial
until deleted: its 90-day expiry is only applied by `manage.py clean`,
which nothing runs. Once `round report` has a verified copy in the
archive, the upload goes; `round drop`, `round prune` and `jobs purge`
delete what is left of theirs.

Artifactorial (the lab's fork) deletes an artifact on
DELETE <base>/artifacts/<path>?token=<token>: 403 if the token's user
may not write it, 404 if it is gone already. The token is the one the
jobs upload with (artifactorial_token in the board files), which owns
/rt-tests. It is never printed: error messages name the path only.
"""

import glob
import os
import urllib.error
import urllib.parse
import urllib.request

import yaml

_MARK = "/artifacts/"


def artifact_path(url):
    """The artifact's path: the part of its URL after /artifacts/."""
    i = url.find(_MARK)
    if i < 0 or not url[i + len(_MARK) :]:
        raise ValueError(f"not an artifactorial URL: {url}")
    return url[i + len(_MARK) :]


def _delete_request(url, token):
    base = url[: url.find(_MARK)]
    path = urllib.parse.quote(artifact_path(url))
    query = urllib.parse.urlencode({"token": token})
    return urllib.request.Request(f"{base}{_MARK}{path}?{query}", method="DELETE")


def delete(url, token, timeout=60, opener=None):
    """Delete the upload at url: "deleted", or "gone" if it was already.

    Raises PermissionError if the token may not delete it, OSError on
    other failures.
    """
    opener = opener or urllib.request.urlopen
    try:
        with opener(_delete_request(url, token), timeout=timeout) as r:
            r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "gone"
        if exc.code == 403:
            raise PermissionError(f"{artifact_path(url)}: not allowed") from None
        raise OSError(f"{artifact_path(url)}: HTTP {exc.code}") from None
    return "deleted"


def upload_token(system_config):
    """The token the jobs upload with: system_config artifactorial-token,
    else artifactorial_token of the first board file that has one."""
    if system_config.get("artifactorial-token"):
        return system_config["artifactorial-token"]
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = sorted(glob.glob(os.path.join(repo, "jobs", "boards", "*.yaml")))
    paths += sorted(glob.glob(os.path.expanduser("~/.config/srt-build/*.yaml")))
    for path in paths:
        try:
            with open(path) as f:
                ctx = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(ctx, dict) and ctx.get("artifactorial_token"):
            return str(ctx["artifactorial_token"])
    raise SystemExit("no artifactorial_token in the board files")


def delete_all(urls, token, delete_fn=None):
    """Delete urls; {url: "deleted" | "gone" | error text}."""
    delete_fn = delete_fn or delete
    out = {}
    for url in urls:
        try:
            out[url] = delete_fn(url, token)
        except OSError as exc:  # PermissionError is one
            out[url] = f"failed: {exc}"
    return out
