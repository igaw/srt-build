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


def test_combined_job_samples_per_test():
    """A combined job's results get the test of their suite, as if each
    test had its own job; kernel-log and other helper suites none."""
    from srt_build.report import summarize_job

    suites = [
        {"id": 1, "name": "lava"},
        {"id": 2, "name": "0_settle"},
        {"id": 3, "name": "1_rtla-timerlat"},
        {"id": 4, "name": "2_kernel-log"},
        {"id": 5, "name": "3_cyclictest"},
    ]
    upload = "reference: http://a.lan/artifacts/x/rtla-timerlat.json\n"
    tests = [
        {"name": "u0-max-latency", "result": "pass", "suite": 3, "measurement": "256"},
        {"name": "t0-max-latency", "result": "pass", "suite": 5, "measurement": "155"},
        {"name": "kernel-log-clean", "result": "pass", "suite": 4, "measurement": "1"},
        {"name": "test-attachment", "result": "pass", "suite": 3, "metadata": upload},
    ]
    job = _job(description="rt-tests")
    s = summarize_job(job, tests, suites)
    assert s.per_test == [("rtla-timerlat", 256.0), ("cyclictest", 155.0)]
    doc = {"thread": {"0": {"histogram": {"10": 5}, "count": 5}}}
    samples = job_samples(job, tests, s, {"rtla-timerlat.json": doc})
    lat = {
        (x["metric"]["test"], x["metric"]["thread"]): x["values"][0]
        for x in samples
        if x["metric"]["__name__"] == "srt_latency_us"
    }
    assert lat == {("rtla-timerlat", "u0"): 256.0, ("cyclictest", "t0"): 155.0}
    assert not [x for x in samples if x["metric"].get("case") == "kernel-log-clean"]
    hist = {
        x["metric"]["test"]
        for x in samples
        if x["metric"]["__name__"] == "srt_latency_bucket"
    }
    assert hist == {"rtla-timerlat"}


def test_same_upload_name_from_two_tests():
    """rtla-timerlat-idle and rtla-timerlat of a combined job both
    upload rtla-timerlat.json: both histograms count, each its test's."""
    from srt_build.report import summarize_job

    from srt_build.metrics import artifact_suites

    suites = [
        {"id": 1, "name": "lava"},
        {"id": 3, "name": "1_rtla-timerlat-idle"},
        {"id": 5, "name": "3_rtla-timerlat"},
        {"id": 6, "name": "4_cyclictest"},
    ]

    def upload(suite, path):
        md = f"reference: http://a.lan/artifacts/{path}\n"
        return {"name": "test-attachment", "result": "pass", "suite": suite,
                "metadata": md}  # fmt: skip

    tests = [
        {"name": "u0-max-latency", "result": "pass", "suite": 3, "measurement": "9"},
        {"name": "u0-max-latency", "result": "pass", "suite": 5, "measurement": "8"},
        upload(3, "12/27/rtla-timerlat.json"),
        upload(5, "12/35/rtla-timerlat.json"),
        upload(6, "12/43/cyclictest.json"),
    ]
    urls = artifact_urls(tests)
    assert urls == {
        "3-rtla-timerlat.json": "http://a.lan/artifacts/12/27/rtla-timerlat.json",
        "5-rtla-timerlat.json": "http://a.lan/artifacts/12/35/rtla-timerlat.json",
        "cyclictest.json": "http://a.lan/artifacts/12/43/cyclictest.json",
    }
    assert artifact_suites(tests) == {
        "3-rtla-timerlat.json": 3,
        "5-rtla-timerlat.json": 5,
        "cyclictest.json": 6,
    }
    job = _job(description="rt-tests")
    s = summarize_job(job, tests, suites)
    doc = {"thread": {"0": {"histogram": {"10": 5}, "count": 5}}}
    samples = job_samples(job, tests, s, {name: doc for name in urls})
    hist = {
        x["metric"]["test"]
        for x in samples
        if x["metric"]["__name__"] == "srt_latency_bucket"
    }
    assert hist == {"rtla-timerlat-idle", "rtla-timerlat", "cyclictest"}


def test_single_test_job_keeps_its_test():
    from srt_build.report import combined_suite_tests

    assert (
        combined_suite_tests(
            [
                {"id": 1, "name": "lava"},
                {"id": 2, "name": "0_cyclictest"},
                {"id": 3, "name": "1_kernel-log"},
            ]
        )
        == {}
    )


def test_workload_names():
    from srt_build.metrics import workload

    assert workload("") == "idle"
    assert workload("hackbench") == "hackbench"
    assert workload("taskset -c 0 hackbench") == "hackbench"
    assert workload("stress-ng -v --access 0") == "stress-ng-access"
    assert (
        workload("stress-ng -v --oom-avoid --class io --seq 0 -t 15 -x a,b")
        == "stress-ng-class-io"
    )
    assert (
        workload(
            "stress-ng --oom-avoid --temp-path /tmp --cpu 1 --vm 1 --vm-bytes 10%"
            " --hdd 1 --hdd-bytes 32M --sock 1 --pipe 1 --switch 1 --fork 1"
        )
        == "stress-ng-mix"
    )


def test_workloads_of_all_templates(monkeypatch):
    """Every template's BACKGROUND_CMD gets a workload name: the
    stress-ng jobs their stressor or class, no rt test "idle" by
    accident."""
    import os
    from types import SimpleNamespace

    import yaml

    from srt_build import config
    from srt_build.helpers import (
        flavor_job_ctx,
        generate_job,
        job_templates,
        load_job_ctx,
    )
    from srt_build.metrics import definition_workloads

    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, "config.yml")) as f:
        cfg = yaml.safe_load(f)
    monkeypatch.setattr(config, "flavors", cfg.get("flavors") or {})
    jobs = os.path.join(root, "jobs")
    board = "rpi3-64"
    ctx = SimpleNamespace(**{"hostname": board, **cfg["machine_config"][board]})
    job_ctx = load_job_ctx(os.path.join(jobs, "boards", board + ".yaml"))
    job_ctx["tags"] = [board]
    found = {}
    for fl in ("rt", "rt-isolcpus"):
        flavor_job_ctx(ctx, fl, job_ctx)
        for sub in sorted(os.listdir(os.path.join(jobs, fl))):
            for path, c in job_templates(os.path.join(jobs, fl, sub), job_ctx):
                job = {"definition": generate_job(jobs, path, c)}
                name = yaml.safe_load(job["definition"])["job_name"]
                found[name] = definition_workloads(job)
    assert found["cyclictest"] == {"cyclictest": "hackbench"}
    assert found["cyclictest rt-isolcpus"] == {"cyclictest": "hackbench"}
    assert found["rtla-timerlat-stress"] == {"rtla-timerlat-stress": "stress-ng-mix"}
    assert found["stress-ng-access"] == {"rtla-timerlat": "stress-ng-access"}
    assert found["stress-ng-io"] == {"rtla-timerlat": "stress-ng-class-io"}
    assert found["isolcpus rt-isolcpus"] == {}
    assert found["rtla-timerlat-idle"] == {"rtla-timerlat-idle": "idle"}
    assert found["cyclictest-idle rt-isolcpus"] == {"cyclictest-idle": "idle"}
    for name, wl in found.items():
        if name.startswith("stress-ng-"):
            # stress-ng-<stressor>, or stress-ng-class-<class> of the
            # class job stress-ng-<class>
            what = name[len("stress-ng-") :]
            assert list(wl.values()) in (
                [f"stress-ng-{what}"],
                [f"stress-ng-class-{what}"],
            ), (name, wl)


def test_samples_carry_workload():
    """A combined job's tests each get their definition's workload; a
    job of one test its one definition's."""
    from srt_build.report import summarize_job

    definition = (
        DEFINITION
        + """
actions:
- test:
    definitions:
    - name: rtla-timerlat
      parameters: {BACKGROUND_CMD: ""}
- test:
    definitions:
    - name: kernel-log
- test:
    definitions:
    - name: cyclictest
      parameters: {BACKGROUND_CMD: "taskset -c 0 hackbench"}
"""
    )
    suites = [
        {"id": 1, "name": "lava"},
        {"id": 3, "name": "0_rtla-timerlat"},
        {"id": 4, "name": "1_kernel-log"},
        {"id": 5, "name": "2_cyclictest"},
    ]
    tests = [
        {"name": "u0-max-latency", "result": "pass", "suite": 3, "measurement": "56"},
        {"name": "t0-max-latency", "result": "pass", "suite": 5, "measurement": "155"},
    ]
    job = _job(description="rt-tests", definition=definition)
    s = summarize_job(job, tests, suites)
    got = {
        x["metric"]["test"]: x["metric"].get("workload")
        for x in job_samples(job, tests, s)
        if x["metric"]["__name__"] == "srt_latency_us"
    }
    assert got == {"rtla-timerlat": "idle", "cyclictest": "hackbench"}

    one = (
        DEFINITION
        + """
actions:
- test:
    definitions:
    - name: cyclictest
      parameters: {BACKGROUND_CMD: "hackbench"}
"""
    )
    job = _job(definition=one)
    tests = [{"name": "t0-max-latency", "result": "pass", "measurement": "15"}]
    samples = job_samples(job, tests, _summary())
    lat = [x for x in samples if x["metric"]["__name__"] == "srt_latency_us"]
    assert lat[0]["metric"]["workload"] == "hackbench"
    ok = [x for x in samples if x["metric"]["__name__"] == "srt_job_ok"]
    assert "workload" not in ok[0]["metric"]
