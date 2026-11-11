"""LAVA job results as VictoriaMetrics samples (srt_build/metrics.py)."""

import json

from srt_build.metrics import (
    BUCKETS,
    artifact_urls,
    histogram_samples,
    job_labels,
    job_samples,
    timestamp_ms,
    to_jsonl,
)
from srt_build.report import JobSummary

DEFINITION = """
job_name: cyclictest rt-isolcpus
metadata:
  srt.board: rpi3-64
  srt.flavor: rt-isolcpus
  srt.test: cyclictest
  srt.kernel: v6.12.117-rt23
  srt.build: f4db30c00000
"""


def _job(**kw):
    job = {
        "id": 300,
        "actual_device": "rpi3-64",
        "description": "cyclictest rt-isolcpus",
        "state": "Finished",
        "health": "Complete",
        "end_time": "2026-11-11T14:11:44.493000Z",
        "definition": DEFINITION,
    }
    job.update(kw)
    return job


def _summary(**kw):
    s = JobSummary(300, "rpi3-64", "cyclictest rt-isolcpus", "Finished", "Complete")
    s.kernel = "6.12.117-rt23"
    for k, v in kw.items():
        setattr(s, k, v)
    return s


TESTS = [
    {
        "name": "0_cyclictest",
        "result": "pass",
        "measurement": "65.79",
        "unit": "seconds",
    },
    {
        "name": "login-action",
        "result": "pass",
        "measurement": "29.89",
        "unit": "seconds",
    },
    {"name": "t1-max-latency", "result": "pass", "measurement": "113.0", "unit": "us"},
    {"name": "i2-avg-latency", "result": "pass", "measurement": "1.5", "unit": "us"},
    {"name": "inversion", "result": "pass", "measurement": "2498392", "unit": "count"},
    {
        "name": "test-attachment",
        "result": "pass",
        "metadata": "case: test-attachment\nreference: http://a.lan/x/cyclictest.json\n",
    },
    {
        "name": "test-attachment",
        "result": "pass",
        "metadata": "reference: http://a.lan/x/osnoise_irq_noise_hist.txt\n",
    },
]


def _by_name(samples, name):
    return [s for s in samples if s["metric"]["__name__"] == name]


def test_labels_from_metadata():
    labels = job_labels(_job(), _summary())
    assert labels == {
        "board": "rpi3-64",
        "flavor": "rt-isolcpus",
        "test": "cyclictest",
        "kernel": "6.12.117-rt23",
        "job": "300",
    }


def test_labels_of_older_jobs_from_description():
    job = _job(definition="job_name: x\n", description="rtla-timerlat rt-isolcpus")
    labels = job_labels(job, _summary())
    assert (labels["test"], labels["flavor"]) == ("rtla-timerlat", "rt-isolcpus")
    job = _job(definition="job_name: x\n", description="pi-stress")
    assert job_labels(job, _summary())["flavor"] == "rt"


def test_timestamp_is_lava_end_time():
    assert timestamp_ms(_job()) == 1794406304493
    assert timestamp_ms(_job(end_time=None, start_time=None)) is None


def test_job_samples():
    samples = job_samples(_job(), TESTS, _summary())
    assert _by_name(samples, "srt_job_ok")[0]["values"] == [1]
    assert _by_name(samples, "srt_job_info")[0]["metric"]["srt_build"] == "f4db30c00000"
    lat = {
        (s["metric"]["thread"], s["metric"]["stat"]): s["values"][0]
        for s in _by_name(samples, "srt_latency_us")
    }
    assert lat == {("t1", "max"): 113.0, ("i2", "avg"): 1.5}
    (inv,) = _by_name(samples, "srt_value")
    assert (inv["metric"]["case"], inv["metric"]["unit"]) == ("inversion", "count")
    # LAVA's own cases (boot, overlays, definitions) are no results
    assert not any("login" in json.dumps(s) for s in samples)
    assert all(s["timestamps"] == [1794406304493] for s in samples)


def test_problems_make_job_not_ok():
    s = _summary(findings=[("kernel", "rcu: INFO: rcu_preempt self-detected stall")])
    samples = job_samples(_job(), TESTS, s)
    assert _by_name(samples, "srt_job_ok")[0]["values"] == [0]
    console = [
        x
        for x in _by_name(samples, "srt_job_problems")
        if x["metric"]["kind"] == "console"
    ]
    assert console[0]["values"] == [1]


def test_histogram_buckets_are_cumulative():
    # cyclictest: thread index keys, overflows only in "cycles"
    doc = {"thread": {"0": {"histogram": {"5": 10, "12": 5, "90": 1}, "cycles": 17}}}
    buckets = {
        s["metric"]["le"]: s["values"][0]
        for s in histogram_samples(doc, {"job": "1"}, 0)
    }
    assert len(buckets) == len(BUCKETS) + 1
    assert (buckets["5"], buckets["10"], buckets["20"], buckets["75"]) == (
        10,
        10,
        15,
        15,
    )
    assert (buckets["100"], buckets["2000"], buckets["+Inf"]) == (16, 16, 17)


def test_histogram_sections_of_rtla():
    hist = {"histogram": {"3": 2}, "count": 2, "over": 0}
    doc = {"thread": {"1": hist}, "irq": {"1": hist}, "user": {"1": hist}}
    threads = {s["metric"]["thread"] for s in histogram_samples(doc, {}, 0)}
    assert threads == {"t1", "i1", "u1"}
    assert histogram_samples({"inversion": 5}, {}, 0) == []


def test_artifact_urls_only_json():
    assert artifact_urls(TESTS) == {"cyclictest.json": "http://a.lan/x/cyclictest.json"}


def test_jsonl():
    samples = job_samples(_job(), TESTS, _summary())
    lines = to_jsonl(samples).splitlines()
    assert len(lines) == len(samples)
    assert json.loads(lines[0])["metric"]["__name__"] == "srt_job_ok"


def test_exportable():
    from srt_build.metrics import exportable

    assert exportable(_job(description="cyclictest"))
    assert exportable(_job(description="rtla-timerlat rt-isolcpus"))
    assert not exportable(_job(description="hack (cyclictest rt-isolcpus)"))
    assert not exportable(_job(description="pi-stress (rcutree.kthread_prio=5)"))
    assert not exportable(_job(description="test-x86-health-check"))
    assert not exportable(_job(description="cyclictest", health_check=True))
