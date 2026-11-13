"""Deleting uploads on Artifactorial, against a fake server."""

import io
import urllib.error

import pytest

from srt_build import artifactorial

URL = "http://artifactorial.invalid:8000/artifacts/rt-tests/2026/11/13/12/27/rtla-timerlat.json"
TOKEN = "FAKE-UPLOAD-TOKEN-0123456789"


class Server:
    def __init__(self, code=200):
        self.code = code
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.code != 200:
            raise urllib.error.HTTPError(req.full_url, self.code, "x", {}, None)
        return io.BytesIO(b"")


def test_artifact_path_from_the_url():
    assert artifactorial.artifact_path(URL) == (
        "rt-tests/2026/11/13/12/27/rtla-timerlat.json"
    )
    with pytest.raises(ValueError):
        artifactorial.artifact_path("http://x.invalid/other/a.json")


def test_delete():
    server = Server()
    assert artifactorial.delete(URL, TOKEN, opener=server) == "deleted"
    (req,) = server.requests
    assert req.get_method() == "DELETE"
    assert req.full_url == (
        "http://artifactorial.invalid:8000/artifacts/rt-tests/2026/11/13/12/27/"
        f"rtla-timerlat.json?token={TOKEN}"
    )


def test_gone_and_forbidden_without_the_token():
    assert artifactorial.delete(URL, TOKEN, opener=Server(404)) == "gone"
    with pytest.raises(PermissionError) as e:
        artifactorial.delete(URL, TOKEN, opener=Server(403))
    assert TOKEN not in str(e.value)
    with pytest.raises(OSError) as e:
        artifactorial.delete(URL, TOKEN, opener=Server(500))
    assert TOKEN not in str(e.value)


def test_delete_all_reports_failures():
    def fake(url, token):
        if "bad" in url:
            raise PermissionError("nope")
        return "deleted"

    assert artifactorial.delete_all(
        ["a/artifacts/x", "bad/artifacts/y"], "t", fake
    ) == {
        "a/artifacts/x": "deleted",
        "bad/artifacts/y": "failed: nope",
    }


def test_token_from_the_config():
    assert artifactorial.upload_token({"artifactorial-token": "t"}) == "t"
