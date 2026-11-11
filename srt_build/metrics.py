"""LAVA job results as VictoriaMetrics samples, for `jobs export`.

Pure functions on data already fetched (job, test cases, summary,
artifacts), so they can be tested without LAVA or VictoriaMetrics.

Every sample of a job carries the job's end time from LAVA, not the
board's clock (the boards have no RTC; their rt-tests JSON says
October), and the labels board, flavor, test, kernel and job.
VictoriaMetrics' /api/v1/import takes such old timestamps, so older
rounds can be exported later the same way.

  srt_job_ok             1 if the job has no problem (`jobs report`)
  srt_job_problems       number of problems, by kind
  srt_job_info           1, with the srt-build version that submitted it
  srt_latency_us         min/avg/max per thread, from LAVA's test cases
  srt_latency_bucket     cumulative histogram (le in us) per thread,
                         from the rt-tests/rtla JSON in artifactorial
  srt_value              any other measured test case (pi-stress
                         inversions), with case and unit
"""

import json
import re
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
    ):
        out.append(_sample("srt_job_problems", {**labels, "kind": kind}, n, ts))
    srt_build = str(job_metadata(job).get("srt.build") or "unknown")
    out.append(_sample("srt_job_info", {**labels, "srt_build": srt_build}, 1, ts))

    for t in tests:
        name = t.get("name", "")
        value = t.get("measurement")
        if value in (None, "") or _LAVA_CASES.match(name):
            continue
        m = _LATENCY.match(name)
        if m:
            extra = {"thread": m.group(1), "stat": m.group(2)}
            out.append(_sample("srt_latency_us", {**labels, **extra}, float(value), ts))
        else:
            extra = {"case": name, "unit": t.get("unit") or ""}
            out.append(_sample("srt_value", {**labels, **extra}, float(value), ts))

    for doc in (artifacts or {}).values():
        out += histogram_samples(doc, labels, ts)
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


def artifact_urls(tests):
    """The JSON files a job uploaded to artifactorial, {name: url}."""
    urls = {}
    for t in tests:
        if t.get("name") != "test-attachment" or t.get("result") != "pass":
            continue
        try:
            md = yaml.safe_load(t.get("metadata") or "") or {}
        except yaml.YAMLError:
            continue
        url = str(md.get("reference") or "") if isinstance(md, dict) else ""
        if url.endswith(".json"):
            urls[url.rsplit("/", 1)[-1]] = url
    return urls


def to_jsonl(samples):
    """The body for VictoriaMetrics' /api/v1/import."""
    return "".join(json.dumps(s, separators=(",", ":")) + "\n" for s in samples)
