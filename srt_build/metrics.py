"""LAVA job results as VictoriaMetrics samples, for `jobs export`.

Pure functions on data already fetched (job, test cases, summary,
artifacts), so they can be tested without LAVA or VictoriaMetrics.

Every sample of a job carries the job's end time from LAVA, not the
board's clock (the boards have no RTC; their rt-tests JSON says
October), and the labels board, flavor, test, kernel and job. A
test's results also carry its workload (see workload()).
VictoriaMetrics' /api/v1/import takes such old timestamps, so older
rounds can be exported later the same way.

  srt_job_ok             1 if the job has no problem (`jobs report`)
  srt_job_problems       number of problems, by kind (and "retried":
                         actions that passed on another attempt, not
                         counted in srt_job_ok)
  srt_job_info           1, with the srt-build version that submitted it
  srt_latency_us         min/avg/max per thread, from LAVA's test cases
  srt_latency_bucket     cumulative histogram (le in us) per thread,
                         from the rt-tests/rtla JSON in artifactorial
  srt_value              any other measured test case (pi-stress
                         inversions), with case and unit
"""

import json
import re
from collections import Counter
from datetime import datetime

import yaml

# Test cases of LAVA itself (overlay, boot, power) aren't results.
_LAVA_CASES = re.compile(
    r"^(\d+_.*|validate|job|test-attachment|git-repo-action|http-download"
    r"|pdu-reboot|kernel-messages|login-action|power-off|auto-login-action"
    r"|.*-overlay|bootloader-.*|.*-action)$"
)
# t0-max-latency (rt-tests, rtla thread), i0- (rtla irq), u0- (rtla user)
_LATENCY = re.compile(r"^([tiu]\d+)-(min|avg|max)-latency$")
# Sections of the rt-tests and rtla JSON and the prefix of their threads
# in LAVA's test case names.
_SECTIONS = {"thread": "t", "irq": "i", "user": "u"}
# Bucket bounds in us. Fixed, so series of all jobs line up and
# histogram_quantile() works across them.
BUCKETS = (5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 2000)


# The job names srt-build submits: "<test>" or "<test> <flavor>". Hack
# sessions ("hack (cyclictest)"), resubmits with extra arguments
# ("cyclictest (nohz=off)") and health checks are debugging, not results.
_ROUND_JOB = re.compile(r"^[\w.-]+( [\w.-]+)?$")


def exportable(job):
    """Whether the job is part of a test round."""
    name = job.get("description") or ""
    return bool(
        _ROUND_JOB.match(name)
        and not name.startswith("hack")
        and not name.split()[0].endswith("health-check")
        and not job.get("health_check")
    )


def job_metadata(job):
    """The srt.* metadata of the job definition ({} for older jobs)."""
    try:
        definition = yaml.safe_load(job.get("definition") or "") or {}
    except yaml.YAMLError:
        return {}
    md = definition.get("metadata") if isinstance(definition, dict) else None
    return md if isinstance(md, dict) else {}


# stress-ng options with a number that aren't stressors.
_SNG_NOT_STRESSORS = {"seq", "timeout", "t", "backoff", "ionice-level", "sched-prio"}


def workload(cmd):
    """The workload a test ran under, from its BACKGROUND_CMD.

    "idle" (none), "hackbench", "stress-ng-class-<class>" (--class),
    "stress-ng-<stressor>" (one stressor) or "stress-ng-mix" (several:
    rtla-timerlat-stress's fixed mix), else the command's name. Pinning
    it to CPUs (taskset -c) doesn't change what it is.
    """
    cmd = re.sub(r"^taskset -c \S+\s+", "", (cmd or "").strip())
    words = cmd.split()
    if not words:
        return "idle"
    name = words[0].rsplit("/", 1)[-1]
    if name != "stress-ng":
        return name
    m = re.search(r"--class[= ](\S+)", cmd)
    if m:
        return f"stress-ng-class-{m.group(1)}"
    stressors = [
        s
        for s in re.findall(r"--([a-z][a-z0-9-]*)[= ](\d+)(?=\s|$)", cmd)
        if s[0] not in _SNG_NOT_STRESSORS
    ]
    if len(stressors) == 1:
        return f"stress-ng-{stressors[0][0]}"
    return "stress-ng-mix"


def definition_workloads(job):
    """{test definition name: workload} of the job's definitions that
    take a BACKGROUND_CMD. A combined job's suites are named after
    their definition, so this gives each of its tests its own."""
    try:
        definition = yaml.safe_load(job.get("definition") or "") or {}
    except yaml.YAMLError:
        return {}
    out = {}
    for action in (
        definition.get("actions") or [] if isinstance(definition, dict) else []
    ):
        for d in ((action or {}).get("test") or {}).get("definitions") or []:
            params = d.get("parameters") or {}
            if "BACKGROUND_CMD" in params:
                out[d.get("name")] = workload(str(params["BACKGROUND_CMD"]))
    return out


def job_labels(job, summary):
    """Labels common to all samples of a job.

    From the job's srt.* metadata; jobs submitted before it existed
    fall back to the description ("cyclictest rt-isolcpus": test and
    flavor, no flavor meaning rt). kernel is the booted release from the
    console, as `jobs report` shows it.
    """
    md = job_metadata(job)
    words = (job.get("description") or "").split()
    return {
        "board": str(md.get("srt.board") or job.get("actual_device") or ""),
        "flavor": str(md.get("srt.flavor") or (words[1] if len(words) > 1 else "rt")),
        "test": str(md.get("srt.test") or (words[0] if words else "")),
        "kernel": summary.kernel or str(md.get("srt.kernel") or ""),
        "job": str(job["id"]),
    }


def timestamp_ms(job):
    """The job's end time (LAVA's clock) in ms since the epoch."""
    t = job.get("end_time") or job.get("start_time") or job.get("submit_time")
    if not t:
        return None
    return int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1000)


def _sample(name, labels, value, ts):
    return {
        "metric": {"__name__": name, **labels},
        "values": [value],
        "timestamps": [ts],
    }


def job_samples(job, tests, summary, artifacts=None):
    """All samples of one finished job.

    tests: its LAVA test cases; summary: its JobSummary (with log);
    artifacts: {file name: parsed JSON} of its rt-tests/rtla uploads.
    """
    ts = timestamp_ms(job)
    if ts is None:
        return []
    labels = job_labels(job, summary)
    out = []

    problems = summary.problems()
    out.append(_sample("srt_job_ok", labels, 0 if problems else 1, ts))
    for kind, n in (
        ("health", int(summary.finished and summary.health != "Complete")),
        ("failed", len(summary.failed)),
        ("uploads", summary.uploads_failed),
        ("no_results", len(summary.no_results)),
        ("console", len(summary.findings)),
        ("retried", len(summary.retried)),  # not a problem, lab health
    ):
        out.append(_sample("srt_job_problems", {**labels, "kind": kind}, n, ts))
    srt_build = str(job_metadata(job).get("srt.build") or "unknown")
    out.append(_sample("srt_job_info", {**labels, "srt_build": srt_build}, 1, ts))

    # A combined job's results belong to the test of their suite, so
    # each test keeps its own series, as with a job per test.
    suite_tests = getattr(summary, "suite_tests", None) or {}

    workloads = definition_workloads(job)
    # A job of one test: the workload of its one definition with a
    # BACKGROUND_CMD (none: isolcpus check, smoke tests).
    single = list(workloads.values()) if len(workloads) == 1 else []

    def test_labels(suite):
        name = suite_tests.get(suite)
        if name:
            wl = workloads.get(name)
            return {**labels, "test": name, **({"workload": wl} if wl else {})}
        return {**labels, "workload": single[0]} if single else labels

    for t in tests:
        name = t.get("name", "")
        value = t.get("measurement")
        if value in (None, "") or _LAVA_CASES.match(name):
            continue
        if suite_tests and t.get("suite") not in suite_tests:
            continue  # kernel-log, fair-server, ... of a combined job
        tl = test_labels(t.get("suite"))
        m = _LATENCY.match(name)
        if m:
            extra = {"thread": m.group(1), "stat": m.group(2)}
            out.append(_sample("srt_latency_us", {**tl, **extra}, float(value), ts))
        else:
            extra = {"case": name, "unit": t.get("unit") or ""}
            out.append(_sample("srt_value", {**tl, **extra}, float(value), ts))

    suites = artifact_suites(tests)
    for fname, doc in (artifacts or {}).items():
        out += histogram_samples(doc, test_labels(suites.get(fname)), ts)
    return out


def histogram_samples(doc, labels, ts):
    """srt_latency_bucket samples of one rt-tests or rtla JSON file.

    Each thread's "histogram" maps us to a count. Samples above the
    histogram's size aren't in it: rtla counts them in "over",
    cyclictest only in "cycles"; both end up in le="+Inf".
    """
    out = []
    if not isinstance(doc, dict):
        return out
    for section, prefix in _SECTIONS.items():
        threads = doc.get(section)
        if not isinstance(threads, dict):
            continue
        for key, th in threads.items():
            if not isinstance(th, dict) or not isinstance(th.get("histogram"), dict):
                continue
            hist = sorted((int(us), int(n)) for us, n in th["histogram"].items())
            total = th.get("count", th.get("cycles"))
            total = int(total) if total is not None else sum(n for _, n in hist)
            thread = {"thread": f"{prefix}{key}"}
            for le in BUCKETS:
                n = sum(c for us, c in hist if us <= le)
                out.append(
                    _sample(
                        "srt_latency_bucket", {**labels, **thread, "le": str(le)}, n, ts
                    )
                )
            out.append(
                _sample(
                    "srt_latency_bucket", {**labels, **thread, "le": "+Inf"}, total, ts
                )
            )
    return out


def artifact_suites(tests):
    """{file name: suite id} of the JSON files a job uploaded."""
    return {key: suite for key, suite, _ in uploads(tests)}


def artifact_urls(tests):
    """The JSON files a job uploaded to artifactorial, {name: url}.

    A name that more than one suite uploaded (a combined job's rtla
    tests all write rtla-timerlat.json, in other minutes, so
    artifactorial doesn't rename them) gets its suite id in front,
    "<suite>-<name>": keyed by the bare name, all but the last test's
    histograms were lost (round 12, jobs 912, 924, 926, 941, 953, 955).
    """
    return {key: url for key, _, url in uploads(tests)}


def uploads(tests):
    """[(name, suite id, url)] of the JSON uploads, names unique."""
    found = []
    for t in tests:
        if t.get("name") != "test-attachment" or t.get("result") != "pass":
            continue
        try:
            md = yaml.safe_load(t.get("metadata") or "") or {}
        except yaml.YAMLError:
            continue
        url = str(md.get("reference") or "") if isinstance(md, dict) else ""
        if url.endswith(".json"):
            found.append((url.rsplit("/", 1)[-1], t.get("suite"), url))
    names = Counter(name for name, _, _ in found)
    return [
        (name if names[name] == 1 else f"{suite}-{name}", suite, url)
        for name, suite, url in found
    ]


def to_jsonl(samples):
    """The body for VictoriaMetrics' /api/v1/import."""
    return "".join(json.dumps(s, separators=(",", ":")) + "\n" for s in samples)
