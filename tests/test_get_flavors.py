"""get_flavors: --flavors is a comma separated list."""

from types import SimpleNamespace

from srt_build.helpers import get_flavors


def ctx(flavors, skip=None):
    c = SimpleNamespace(args=SimpleNamespace(flavors=flavors), hostname="board")
    if skip is not None:
        c.skip_flavors = skip
    return c


def test_default():
    assert get_flavors(ctx(None)) == ["rt", "nohz", "vp", "ll", "up", "lazy"]


def test_comma_list():
    assert get_flavors(ctx("rt,nohz,vp")) == ["rt", "nohz", "vp"]


def test_spaces_and_empty_items():
    assert get_flavors(ctx(" rt , up,")) == ["rt", "up"]


def test_skip_flavors_default_list():
    assert get_flavors(ctx(None, ["up", "lazy"])) == ["rt", "nohz", "vp", "ll"]


def test_skip_flavors_explicit_list():
    assert get_flavors(ctx("rt,lazy", ["lazy"])) == ["rt"]
