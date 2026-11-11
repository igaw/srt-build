"""The rt-tests dashboards (srt_build/grafana.py) are well-formed, link
to each other and only ask for what `jobs export` sends."""

import json
import re

import pytest

from srt_build.grafana import DETAIL_UID, OVERVIEW_UID, build_all, queries

ALL = build_all("http://lava.example:10070")
DASHBOARDS = list(ALL.values())
METRICS = {
    "srt_job_ok",
    "srt_job_problems",
    "srt_job_info",
    "srt_latency_us",
    "srt_latency_bucket",
    "srt_value",
}
LABELS = {"board", "flavor", "test", "kernel", "job", "thread", "stat", "le"}
LABELS |= {"kind", "srt_build", "case", "unit"}


def test_files():
    assert set(ALL) == {"rt-tests.json", "rt-test-detail.json"}
    assert {d["uid"] for d in DASHBOARDS} == {OVERVIEW_UID, DETAIL_UID}


@pytest.mark.parametrize("d", DASHBOARDS, ids=lambda d: d["uid"])
def test_json_and_ids(d):
    json.dumps(d)
    ids = [p["id"] for p in d["panels"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("d", DASHBOARDS, ids=lambda d: d["uid"])
def test_layout_fits_the_grid(d):
    for p in d["panels"]:
        g = p["gridPos"]
        assert g["x"] >= 0 and g["x"] + g["w"] <= 24, p["title"]


@pytest.mark.parametrize("d", DASHBOARDS, ids=lambda d: d["uid"])
def test_queries_balanced_and_known(d):
    for q in queries(d):
        expr = q["expr"]
        for a, b in ("()", "{}", "[]"):
            assert expr.count(a) == expr.count(b), expr
        for name in re.findall(r"\b(srt_\w+)[{\[]", expr):
            assert name in METRICS, expr
        for label in re.findall(r"(\w+)=~?\"", expr):
            assert label in LABELS, expr
        for by in re.findall(r"by \(([^)]*)\)", expr):
            for label in by.split(","):
                assert label.strip() in LABELS, expr


@pytest.mark.parametrize("d", DASHBOARDS, ids=lambda d: d["uid"])
def test_variables_used_are_defined(d):
    names = {v["name"] for v in d["templating"]["list"]}
    texts = [q["expr"] for q in queries(d)]
    texts += [p["title"] for p in d["panels"]]
    texts += ["$" + p["repeat"] for p in d["panels"] if p.get("repeat")]
    for text in texts:
        for var in re.findall(r"\$(\w+)", text):
            if not var.startswith("__"):
                assert var in names, text


def test_overview_has_a_trend_per_board_and_test():
    d = ALL["rt-tests.json"]
    rows = [p for p in d["panels"] if p.get("repeat") == "board"]
    assert len(rows) == 1 and rows[0]["type"] == "row"
    trends = [p for p in d["panels"] if p.get("repeat") == "test"]
    assert len(trends) == 1 and trends[0]["type"] == "timeseries"
    expr = trends[0]["targets"][0]["expr"]
    assert 'board="$board"' in expr and 'test="$test"' in expr


def test_links_between_dashboards_and_to_lava():
    overview = json.dumps(ALL["rt-tests.json"])
    detail = json.dumps(ALL["rt-test-detail.json"])
    assert f"/d/{DETAIL_UID}/rt-test-detail?var-board=$board" in overview
    assert f"/d/{OVERVIEW_UID}" in detail
    for text in (overview, detail):
        assert "http://lava.example:10070/scheduler/job/${__value.raw}" in text
    assert "var-job=${__value.raw}" in detail


def test_detail_shows_one_board_flavor_and_test():
    d = ALL["rt-test-detail.json"]
    single = {v["name"] for v in d["templating"]["list"] if not v["multi"]}
    assert {"board", "flavor", "test", "job"} <= single
    for q in queries(d):
        if "panel" in q and "srt_" in q["expr"]:
            assert 'board="$board"' in q["expr"], q
