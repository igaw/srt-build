"""The rt-tests dashboard (srt_build/grafana.py) is well-formed and only
asks for what `jobs export` sends."""

import json
import re

from srt_build.grafana import build, queries

D = build("http://lava.example:10070")
METRICS = {
    "srt_job_ok",
    "srt_job_problems",
    "srt_job_info",
    "srt_latency_us",
    "srt_latency_bucket",
    "srt_value",
}
LABELS = {"board", "flavor", "test", "kernel", "job", "thread", "stat", "le"}
LABELS |= {"kind", "srt_build", "case", "unit", "what"}


def test_json_and_ids():
    json.dumps(D)
    ids = [p["id"] for p in D["panels"]]
    assert len(ids) == len(set(ids))


def test_layout_fits_the_grid():
    for p in D["panels"]:
        g = p["gridPos"]
        assert g["x"] >= 0 and g["x"] + g["w"] <= 24, p["title"]


def test_queries_balanced_and_known():
    for q in queries(D):
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


def test_variables_used_are_defined():
    names = {v["name"] for v in D["templating"]["list"]}
    for q in queries(D):
        for var in re.findall(r"\$(\w+)", q["expr"]):
            if var.startswith("__"):
                continue
            assert var in names, q


def test_job_links_go_to_lava():
    text = json.dumps(D)
    assert "http://lava.example:10070/scheduler/job/${__value.raw}" in text
