"""get_flavors: --flavors is a comma separated list."""

from types import SimpleNamespace

import pytest

from srt_build import config
from srt_build.helpers import (
    expand_cpus,
    flavor_job_ctx,
    flavor_kernel,
    flavor_kernel_args,
    get_flavors,
)


def ctx(flavors, skip=None):
    c = SimpleNamespace(args=SimpleNamespace(flavors=flavors), hostname="board")
    if skip is not None:
        c.skip_flavors = skip
    return c


def test_default():
    assert get_flavors(ctx(None)) == [
        "rt",
        "rt-isolcpus",
        "nohz",
        "vp",
        "ll",
        "up",
        "lazy",
    ]


def test_comma_list():
    assert get_flavors(ctx("rt,nohz,vp")) == ["rt", "nohz", "vp"]


def test_spaces_and_empty_items():
    assert get_flavors(ctx(" rt , up,")) == ["rt", "up"]


def test_skip_flavors_default_list():
    assert get_flavors(ctx(None, ["up", "lazy"])) == [
        "rt",
        "rt-isolcpus",
        "nohz",
        "vp",
        "ll",
    ]


def test_skip_flavors_explicit_list():
    assert get_flavors(ctx("rt,lazy", ["lazy"])) == ["rt"]


FLAVORS = {
    "rt-isolcpus": {
        "kernel": "rt",
        "needs_isolcpus": True,
        "kernel_args": "nohz_full={isolcpus} irqaffinity={housekeeping}",
    },
    "nohz": {"kernel_args": "nohz_full={isolcpus}"},
}


@pytest.fixture
def flavors(monkeypatch):
    monkeypatch.setattr(config, "flavors", FLAVORS)


def board(isolcpus=None, kernel_args=None, flavors=None):
    c = ctx(flavors)
    if isolcpus:
        c.isolcpus = isolcpus
        c.housekeeping_cpus = "0"
    if kernel_args:
        c.kernel_args = kernel_args
    return c


def test_isolcpus_flavors_need_isolcpus(flavors):
    assert "rt-isolcpus" not in get_flavors(board())
    assert "rt-isolcpus" in get_flavors(board("1-3"))


def test_builds_only_leaves_out_flavors_with_another_kernel(flavors):
    assert "rt-isolcpus" not in get_flavors(board("1-3"), builds_only=True)
    assert flavor_kernel("rt-isolcpus") == "rt"
    assert flavor_kernel("nohz") == "nohz"


def test_kernel_args(flavors):
    b = board("1-3", {"rt-isolcpus": "processor.max_cstate=1"})
    assert flavor_kernel_args(b, "rt-isolcpus") == (
        "nohz_full=1-3 irqaffinity=0 processor.max_cstate=1"
    )
    assert flavor_kernel_args(b, "nohz") == "nohz_full=1-3"
    assert flavor_kernel_args(b, "vp") == ""
    # without isolated CPUs the nohz_full= argument is left out
    assert flavor_kernel_args(board(), "nohz") == ""


def test_flavor_job_ctx(flavors):
    jc = flavor_job_ctx(board("1-3"), "rt-isolcpus", {})
    assert jc["isolcpus_count"] == 3
    assert jc["isolcpus_first"] == 1
    assert jc["housekeeping_mask"] == 1


def test_expand_cpus():
    assert expand_cpus("0,2-3") == [0, 2, 3]
    assert expand_cpus("1") == [1]
