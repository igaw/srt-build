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
LABELS |= {"kind", "srt_build", "case", "unit", "round", "round_kind", "key"}
LABELS |= {"workload", "series"}


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


def test_overview_has_a_round_trend_per_board_and_test():
    """Rounds on the x axis, not time: no time series in the overview."""
    d = ALL["rt-tests.json"]
    rows = [p for p in d["panels"] if p.get("repeat") == "board"]
    assert len(rows) == 1 and rows[0]["type"] == "row"
    trends = [p for p in d["panels"] if p.get("repeat") == "test"]
    assert [p["type"] for p in trends] == ["trend"]
    assert not [p for p in d["panels"] if p["type"] == "timeseries"]
    expr = trends[0]["targets"][0]["expr"]
    assert 'board="$board"' in expr and 'test="$test"' in expr
    assert trends[0]["links"][0]["url"].startswith(f"/d/{DETAIL_UID}/")


def test_rounds_on_the_x_axis():
    """The Trend panel: a row per round and flavor/workload from an
    instant query, pivoted to a column per flavor and workload, round
    made a number. Release rounds only: a test round (t3) isn't one."""
    d = ALL["rt-tests.json"]
    (p,) = [p for p in d["panels"] if p["type"] == "trend"]
    t = p["targets"][0]
    assert t["instant"] and t["format"] == "table"
    assert t["expr"].startswith(
        "label_join(max by (round, flavor, workload) (max_over_time("
    )
    assert '"series", " ", "flavor", "workload")' in t["expr"]
    assert 'round_kind="release"' in t["expr"]
    assert 'workload=~"$workload"' in t["expr"]
    ids = [x["id"] for x in p["transformations"]]
    assert ids == ["groupingToMatrix", "organize", "convertFieldType", "sortBy"]
    assert p["transformations"][1]["options"]["renameByName"] == {
        "round\\series": "Round"
    }
    assert p["options"]["xField"] == "Round"
    (bars,) = [p for p in d["panels"] if p["type"] == "barchart"]
    assert [t["legendFormat"] for t in bars["targets"]] == ["$round_a", "$round_b"]
    for t in bars["targets"]:
        assert '"key", " ", "board", "test", "workload")' in t["expr"]


@pytest.mark.parametrize("d", DASHBOARDS, ids=lambda d: d["uid"])
def test_release_rounds_by_default(d):
    """Test rounds stay out unless chosen (the round trends: release
    only); samples without a round (jobs export) stay in."""
    (v,) = [v for v in d["templating"]["list"] if v["name"] == "round_kind"]
    assert v["current"]["value"] == "release"
    for q in queries(d):
        if "panel" in q and "srt_" in q["expr"]:
            assert "round_kind=~" in q["expr"] or (
                q["panel"] == "$test" and 'round_kind="release"' in q["expr"]
            ), q


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


def test_only_tests_with_latencies_get_trends():
    """smoke-tests, isolcpus and pi-stress have no latencies: no empty
    panels for them, but their problems still count."""
    for d in DASHBOARDS:
        test = next(v for v in d["templating"]["list"] if v["name"] == "test")
        assert "srt_latency_us" in test["definition"]
    overview = ALL["rt-tests.json"]
    problems = next(p for p in overview["panels"] if p["type"] == "table")
    assert "$test" not in problems["targets"][0]["expr"]


@pytest.mark.parametrize("d", DASHBOARDS, ids=lambda d: d["uid"])
def test_workload_all_matches_missing_label(d):
    """All is .*: it keeps samples without a workload (Grafana's own All
    lists the values, which a missing label doesn't match)."""
    (v,) = [v for v in d["templating"]["list"] if v["name"] == "workload"]
    assert v["allValue"] == ".*" and v["includeAll"]
    for q in queries(d):
        if "panel" in q and "srt_latency" in q["expr"]:
            assert 'workload=~"$workload"' in q["expr"], q


def test_overview_spans_a_year():
    """The round trends take everything in the range."""
    assert ALL["rt-tests.json"]["time"]["from"] == "now-1y"
    assert ALL["rt-test-detail.json"]["time"]["from"] == "now-90d"
