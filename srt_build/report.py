"""Summaries of LAVA jobs for `jobs report` and `jobs watch`.

Everything here works on data already fetched (job, test results,
suites, log text), so it can be tested without a LAVA server.

A job can end "Complete" and still be broken: a test script that
crashes leaves no results, an upload that fails is only a
test-attachment case, a kernel warning is only in the console output.
The summary therefore also looks at missing results, uploads and the
board's console output.
"""

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field

import yaml

# What to look for in the board's console output. The first group are
# kernel problems, the second test definitions that broke on the board.
SCAN_PATTERNS = [
    ("kernel", r"WARNING: CPU: \d+ PID: \d+ at \S+ \S+"),
    ("kernel", r"BUG: [^\n]{0,80}"),
    ("kernel", r"Oops[^\n]{0,60}"),
    ("kernel", r"Kernel panic[^\n]{0,60}"),
    ("kernel", r"INFO: task \S+ blocked[^\n]{0,40}"),
    ("kernel", r"rcu: INFO[^\n]{0,60}"),
    ("kernel", r"hung_task[^\n]{0,40}"),
    # Measurements taken while memory ran out are worthless.
    ("kernel", r"\S+ invoked oom-killer"),
    ("test", r"Traceback \(most recent call last\)"),
    (
        "test",
        r"\b(?:Value|Type|Key|Index|Attribute|Name|FileNotFound|ZeroDivision)"
        r"Error: [^\n]{0,70}",
    ),
    ("test", r"Could not set /dev/\S+"),
    ("test", r"curl: \(\d+\)[^\n]{0,50}"),
    ("test", r"\S+: command not found"),
]
_SCAN = [(kind, re.compile(rx)) for kind, rx in SCAN_PATTERNS]
# Kernel warnings that are expected, as regexes on the warning's line;
# the job template's kernel-log check leaves them out too. They may only
# be here when they are harmless on every board.
KNOWN_KERNEL_WARNINGS = [
    # The up flavor (NR_CPUS=1) on a board with more CPUs in its device
    # tree: "DT /cpu 2 nodes greater than max cores 1, capping them".
    r"arm_dt_init_cpu_maps",
]
_KNOWN = re.compile("|".join(KNOWN_KERNEL_WARNINGS))
# Details that differ between occurrences of the same problem.
_NORMALIZE = re.compile(r"CPU: \d+ PID: \d+ ")
_KERNEL_VERSION = re.compile(r"Linux version (\S+)")
# The lava suite has one case per test definition run: "<n>_<name>".
_DEFINITION_CASE = re.compile(r"^\d+_\S+$")
# A max latency above this is never normal on any board (round 10's
# worst was bbb rtla-osnoise, 536 us) and needs a look, even in a
# Complete job: the stress-ng pilot (jobs 716-727) completed with
# 3.8 ms, 48 ms and 15 s. Not a regression check, which needs the
# per-board band, only a floor under it.
LATENCY_ALARM_US = 1000
# LAVA's boot actions (u-boot, iPXE), the ones failure_retry repeats.
_BOOT_ACTION = re.compile(
    r"^(bootloader-\S+|uboot-\S+|u-boot-\S+|ipxe-\S+|pdu-reboot|reset-device"
    r"|auto-login-action|login-action)$"
)


def parse_log(text):
    """Parse a LAVA job log into a list of {"lvl", "msg", ...} entries.

    Each line is "- {...}", a YAML flow mapping that is nearly always
    plain JSON; JSON is much faster, YAML is the fallback.
    """
    entries = []
    for line in text.splitlines():
        if not line.startswith("- {"):
            continue
        body = line[2:]
        try:
            entries.append(json.loads(body))
        except ValueError:
            try:
                entry = yaml.safe_load(body)
            except yaml.YAMLError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def console_lines(entries):
    """The board's own output (not LAVA's messages)."""
    return [
        e["msg"]
        for e in entries
        if e.get("lvl") in ("target", "feedback") and isinstance(e.get("msg"), str)
    ]


def scan_console(lines):
    """Kernel warnings and test-script errors in the console output.

    Returns a list of (kind, text), one per distinct problem.
    """
    found = []
    for line in lines:
        if _KNOWN.search(line):
            continue
        for kind, rx in _SCAN:
            m = rx.search(line)
            if m:
                found.append((kind, _NORMALIZE.sub("", m.group(0)).strip()[:110]))
    return list(dict.fromkeys(found))


def kernel_version(lines):
    for line in lines:
        m = _KERNEL_VERSION.search(line)
        if m:
            return m.group(1)
    return ""


@dataclass
class JobSummary:
    id: int
    device: str
    description: str
    state: str
    health: str
    kernel: str = ""
    failed: list = field(default_factory=list)
    uploads: int = 0
    uploads_failed: int = 0
    max_latency: float = None
    latency_unit: str = ""
    no_results: list = field(default_factory=list)
    error: str = ""
    findings: list = field(default_factory=list)
    retried: list = field(default_factory=list)
    # Combined jobs (several tests in one boot): {suite id: test} of
    # the measuring suites and [(test, max latency)] in run order.
    suite_tests: dict = field(default_factory=dict)
    per_test: list = field(default_factory=list)

    @property
    def finished(self):
        return self.state == "Finished"

    def problems(self):
        """Why this job needs a look; empty if it doesn't."""
        out = []
        if self.finished and self.health != "Complete":
            out.append(self.health + (f": {self.error}" if self.error else ""))
        if self.failed:
            out.append("failed: " + ", ".join(self.failed))
        if self.uploads_failed:
            out.append(f"{self.uploads_failed} of {self.uploads} uploads failed")
        if self.no_results:
            out.append("no results: " + ", ".join(self.no_results))
        if self.findings:
            out.append(f"{len(self.findings)} console findings")
        if (
            self.max_latency is not None
            and self.latency_unit in ("", "us")
            and self.max_latency > LATENCY_ALARM_US
        ):
            out.append(f"max latency {self.max_latency:.0f} us > {LATENCY_ALARM_US}")
        return out

    def to_dict(self):
        d = asdict(self)
        d["problems"] = self.problems()
        return d


def _metadata(test):
    try:
        md = yaml.safe_load(test.get("metadata") or "")
    except yaml.YAMLError:
        return {}
    return md if isinstance(md, dict) else {}


def summarize_job(job, tests, suites=None, log_text=None):
    """Condense one job into a JobSummary.

    job: the job object of the REST API; tests: its test cases;
    suites: its suites (to find test definitions without results);
    log_text: the raw job log (to scan the console output).
    """
    s = JobSummary(
        id=job["id"],
        device=job.get("actual_device") or "-",
        description=job.get("description") or "",
        state=job.get("state", ""),
        health=job.get("health", ""),
    )

    # bbb boots with failure_retry: a failed attempt leaves its failed
    # boot actions (bootloader-commands, uboot-commands, ...) behind, the
    # attempt that worked adds no case for them (job 573). A failed boot
    # action in a job that still completed is such a retry, not a
    # failure: a boot that failed for good makes the job Incomplete.
    failed = {t["name"] for t in tests if t["result"] == "fail"}
    failed -= {"test-attachment", "job"}
    retried = set()
    if s.health == "Complete":
        retried = {n for n in failed if _BOOT_ACTION.match(n)}
    s.retried = sorted(retried)
    s.failed = sorted(failed - retried)
    uploads = [t for t in tests if t["name"] == "test-attachment"]
    s.uploads = len(uploads)
    s.uploads_failed = sum(t["result"] == "fail" for t in uploads)

    latencies = [
        t for t in tests if t["name"].endswith("max-latency") and t.get("measurement")
    ]
    if latencies:
        worst = max(latencies, key=lambda t: float(t["measurement"]))
        s.max_latency = float(worst["measurement"])
        s.latency_unit = worst.get("unit") or ""

    for t in tests:
        if t["name"] == "job" and t["result"] == "fail":
            s.error = str(_metadata(t).get("error_msg", ""))[:120]

    if suites is not None:
        s.no_results = _definitions_without_results(tests, suites)
        s.suite_tests = combined_suite_tests(suites)
        for sid, name in s.suite_tests.items():
            lat = [float(t["measurement"]) for t in latencies if t["suite"] == sid]
            s.per_test.append((name, max(lat) if lat else None))

    if log_text:
        lines = console_lines(parse_log(log_text))
        s.kernel = kernel_version(lines)
        s.findings = scan_console(lines)
    return s


# Suites of a combined job that run no test of their own.
_HELPER_SUITES = {"lava", "kernel-log", "fair-server", "fair-server-on", "settle"}


def combined_suite_tests(suites):
    """{suite id: test name} of a combined job's tests, in run order.

    LAVA names a job's suites "<n>_<definition name>". A job with more
    than one measuring suite is a combined job (combined.py); for a job
    with one test this is {}, and the job's own test name applies.
    """
    found = []
    for su in suites or []:
        m = _DEFINITION_CASE.match(su.get("name") or "")
        if not m:
            continue
        name = su["name"].split("_", 1)[1]
        if name in _HELPER_SUITES or name.startswith("kernel-log-"):
            continue
        found.append((int(su["name"].split("_", 1)[0]), su["id"], name))
    if len(found) < 2:
        return {}
    return {sid: name for _, sid, name in sorted(found)}


def _definitions_without_results(tests, suites):
    """Test definitions that ran but reported nothing.

    That is what a test script crashing after the measurement looks
    like (e.g. a parser error): the definition itself passes in the
    lava suite, its own suite has no cases besides the uploads.
    """
    suite_ids = {s["name"]: s["id"] for s in suites}
    lava_id = suite_ids.get("lava")
    counted = defaultdict(int)
    for t in tests:
        if t["name"] != "test-attachment":
            counted[t["suite"]] += 1
    missing = []
    for t in tests:
        if t["suite"] != lava_id or not _DEFINITION_CASE.match(t["name"]):
            continue
        if t["result"] != "pass":
            continue  # already reported as failed
        if counted.get(suite_ids.get(t["name"]), 0) == 0:
            missing.append(t["name"].split("_", 1)[1])
    return sorted(missing)


def _fmt_latency(s):
    if s.max_latency is None:
        return "-"
    unit = "" if s.latency_unit in ("", "us") else s.latency_unit
    return f"{s.max_latency:.0f}{unit}"


def _fmt_uploads(s):
    if not s.uploads:
        return "-"
    if s.uploads_failed:
        return f"{s.uploads_failed}/{s.uploads} x"
    return f"{s.uploads} ok"


def _report_rows(summaries):
    """One row per job; a combined job adds an indented row per test."""
    rows = []
    for s in summaries:
        health = s.health if s.finished else s.state
        rows.append(
            [
                str(s.id),
                s.device,
                s.description[:30],
                health,
                _fmt_latency(s),
                _fmt_uploads(s),
                "; ".join(
                    s.problems()
                    + (["retried: " + ", ".join(s.retried)] if s.retried else [])
                ),
            ]
        )
        for name, lat in s.per_test:
            rows.append(
                ["", "", "  " + name, "", "-" if lat is None else f"{lat:.0f}", "", ""]
            )
    return rows


def format_report(summaries):
    """The report as text: one row per job, then findings and a summary."""
    headers = ["job", "device", "test", "health", "max us", "uploads", "problems"]
    rows = _report_rows(summaries)
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r[:-1]):
            widths[i] = max(widths[i], len(cell))
    lines = []
    for r in [headers] + rows:
        cells = [c.rjust(widths[0]) if i == 0 else c for i, c in enumerate(r)]
        lines.append(
            "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells[:-1]))
            + "  "
            + cells[-1]
        )

    kernels = sorted({s.kernel for s in summaries if s.kernel})
    if kernels:
        lines += ["", "kernels: " + ", ".join(kernels)]

    findings = defaultdict(list)
    for s in summaries:
        for kind, text in s.findings:
            findings[(kind, text)].append(s.id)
    if findings:
        lines += ["", "console findings:"]
        for (kind, text), ids in sorted(findings.items()):
            lines.append(f"  [{kind}] {text}  (jobs {_id_ranges(ids)})")

    lines += ["", summary_line(summaries)]
    return "\n".join(lines)


def summary_line(summaries):
    finished = [s for s in summaries if s.finished]
    health = defaultdict(int)
    for s in finished:
        health[s.health] += 1
    parts = [f"{len(summaries)} jobs"]
    parts += [f"{n} {h}" for h, n in sorted(health.items())]
    pending = len(summaries) - len(finished)
    if pending:
        parts.append(f"{pending} not finished")
    bad = [s.id for s in summaries if s.problems()]
    parts.append(f"problems in jobs {_id_ranges(bad)}" if bad else "no problems")
    return ", ".join(parts)


def _id_ranges(ids):
    """[5, 6, 7, 9] -> "5-7, 9"."""
    ids = sorted(set(ids))
    out = []
    start = prev = None
    for i in ids:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = i
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return ", ".join(out)


def parse_id_list(spec):
    """'13-20,25' -> [13, ..., 20, 25]."""
    ids = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            ids += range(int(a), int(b) + 1)
        else:
            ids.append(int(part))
    return ids
