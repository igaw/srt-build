"""No test talks to the lab: LAVA, Artifactorial and VictoriaMetrics
are real servers whose data a test must never change. Any HTTP request
a test doesn't fake fails."""

import urllib.request

import pytest


def _no_network(*args, **kwargs):
    raise RuntimeError("a test tried to reach the network")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)


@pytest.fixture
def deleted(monkeypatch):
    """Fake Artifactorial deletion: the URLs deleted, in order."""
    from srt_build import artifactorial

    urls = []

    def fake(url, token, **kwargs):
        assert token == "FAKE-UPLOAD-TOKEN"
        urls.append(url)
        return "deleted"

    monkeypatch.setattr(artifactorial, "delete", fake)
    return urls
