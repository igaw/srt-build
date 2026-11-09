"""get_flavors: --flavors is a comma separated list."""

from types import SimpleNamespace

from srt_build.helpers import get_flavors


def ctx(flavors):
    return SimpleNamespace(args=SimpleNamespace(flavors=flavors))


def test_default():
    assert get_flavors(ctx(None)) == ["rt", "nohz", "vp", "ll", "up"]


def test_comma_list():
    assert get_flavors(ctx("rt,nohz,vp")) == ["rt", "nohz", "vp"]


def test_spaces_and_empty_items():
    assert get_flavors(ctx(" rt , up,")) == ["rt", "up"]
