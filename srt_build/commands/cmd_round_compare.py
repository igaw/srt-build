"""round compare - two rounds side by side, from the archive.

  srt-build round compare 12 13     13 against 12
  srt-build round compare 13        13 against the round before it
  srt-build round compare           the newest release round against
                                    the one before it
  srt-build round compare --check   exit 1 on a regression

One line per board, flavor, test and workload both rounds have: the max
latency in each round, the change, and "regression" where B is above A
by at least compare-min-percent (40) and compare-min-us (20 us), the
rule of doc/TUNING.md; then what only one round has, and the jobs with
problems in either. Jobs a rerun replaced are left out, as everywhere.

"The round before" B is the round of B's kind (release or test) with
jobs that started last before B. --check exits with 1 on a regression
or when a job of B is not Complete or not in the archive: the pass or
fail of a release test (stable-rt-tools `srt test`). Problems `round
report` flags in both rounds alike (e.g. a max latency above 1 ms) don't
fail it on their own. --result FILE writes that result as JSON for srt
test (status pass or fail, a summary line, the rounds, the regressions
and, with grafana-url in the configuration, the rounds-compared
dashboard of both).
"""

import json
import os

import sys

from ..archive import (
    RELEASE,
    ArchiveApi,
    archive_path,
    counted_jobs,
    load_round,
    parse_round,
    round_dir,
    round_ids,
    round_kind,
)
from ..grafana import COMPARE_UID
from ..metrics import definition_workloads, job_labels
from ..report import summarize_job
from .cmd_round import add_json_arg, print_json

# doc/TUNING.md: "more than 40 % *and* more than 20 us above the reference"
MIN_PERCENT = 40
MIN_US = 20
KEY = ("board", "flavor", "test", "workload")


def add_parsers(sub):
    p = sub.add_parser("compare", help="two rounds side by side")
    p.add_argument(
        "a",
        nargs="?",
        help="the reference round: 12 (release), t3 (test); "
        "with only one round given, that one is B",
    )
    p.add_argument(
        "b",
        nargs="?",
        help="the round to judge (default: the newest release round; "
        "A: the round of its kind before it)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="exit 1 on a regression or a job of B not Complete",
    )
    p.add_argument(
        "--result",
        metavar="FILE",
        help="write the result as JSON to FILE, for srt test "
        '(--result "$SRT_TEST_RESULT"); empty: none',
    )
    add_json_arg(p)
    p.set_defaults(func=cmd_round_compare)


def _started(archive, rid):
    return str(load_round(archive, rid).get("started"))


def _with_jobs(archive, kind):
    """The rounds of kind with jobs, in the order they started."""
    ids = [r for r in round_ids(archive, kind) if counted_jobs(load_round(archive, r))]
    return sorted(ids, key=lambda r: _started(archive, r))


def round_before(archive, rid):
    """The round of rid's kind with jobs that started last before rid."""
    start = _started(archive, rid)
    before = [
        r for r in _with_jobs(archive, round_kind(rid)) if _started(archive, r) < start
    ]
    if not before:
        raise SystemExit(f"no round before {rid} to compare with")
    return before[-1]


def pick_rounds(archive, a=None, b=None):
    """(A, B) of the command line: both given, B only (the first
    argument), or none (the newest release round)."""
    if a is not None and b is not None:
        return parse_round(a), parse_round(b)
    if a is not None:
        b = parse_round(a)
        load_round(archive, b)  # exits if there is none
    else:
        ids = _with_jobs(archive, RELEASE)
        if not ids:
            raise SystemExit(f"no release rounds in {archive}")
        b = ids[-1]
    return round_before(archive, b), b


def round_results(archive, rid):
    """({(board, flavor, test, workload): max latency}, [problem lines],
    [the jobs not Complete or not in the archive])."""
    info = load_round(archive, rid)
    a = ArchiveApi(round_dir(archive, rid))
    out, problems, bad = {}, [], []
    for jid in counted_jobs(info):
        if not a.has(jid):
            problems.append(f"job {jid}: not in the archive")
            bad.append(problems[-1])
            continue
        job, tests = a.job(jid), a.tests(jid)
        s = summarize_job(job, tests, a.suites(jid), a.log(jid))
        labels = job_labels(job, s)
        workloads = definition_workloads(job)
        board, flavor = labels["board"], labels["flavor"]
        if s.per_test:
            for name, lat in s.per_test:
                out[(board, flavor, name, workloads.get(name, ""))] = lat
        else:
            wl = next(iter(workloads.values())) if len(workloads) == 1 else ""
            out[(board, flavor, labels["test"], wl)] = s.max_latency
        if s.problems():
            problems.append(f"job {jid} {board} {labels['test']}: "
                            + "; ".join(s.problems()))  # fmt: skip
        health = job.get("health") or job.get("state") or "unknown"
        if health != "Complete":
            bad.append(f"job {jid} {board} {labels['test']}: {health}")
    return out, problems, bad


def thresholds(system_config):
    """(min percent, min us) of a regression, from the configuration."""
    return (
        float(system_config.get("compare-min-percent", MIN_PERCENT)),
        float(system_config.get("compare-min-us", MIN_US)),
    )


def is_regression(va, vb, min_percent=MIN_PERCENT, min_us=MIN_US):
    """B above A by at least min_percent and at least min_us. Only a
    longer latency counts: a shorter one is never a regression."""
    if not va or vb is None:
        return False
    return (vb - va) / va * 100 >= min_percent and vb - va >= min_us


def compare_rows(ra, rb, min_percent=MIN_PERCENT, min_us=MIN_US):
    """The rows both rounds have, as dicts; the keys only in A and only
    in B."""
    rows = []
    for key in sorted(set(ra) & set(rb)):
        va, vb = ra[key], rb[key]
        change = round((vb - va) / va * 100, 1) if va and vb is not None else None
        rows.append(
            {
                **dict(zip(KEY, key, strict=True)),
                "a": va,
                "b": vb,
                "change_percent": change,
                "regression": is_regression(va, vb, min_percent, min_us),
            }
        )
    return rows, sorted(set(ra) - set(rb)), sorted(set(rb) - set(ra))


def _fmt(v):
    return "-" if v is None else f"{v:.0f}"


def compare_lines(rows, a, b):
    table = [[*KEY, str(a), str(b), "change", ""]]
    for r in rows:
        c = r["change_percent"]
        table.append(
            [*(r[k] for k in KEY), _fmt(r["a"]), _fmt(r["b"]),
             "" if c is None else f"{c:+.0f}%",
             "regression" if r["regression"] else ""]
        )  # fmt: skip
    widths = [max(len(r[i]) for r in table) for i in range(len(table[0]))]
    return [
        "  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip()
        for r in table
    ]


def compare_json(rows, only_a, only_b, a, b, problems, bad, kernels):
    a, b = str(a), str(b)
    regressions = [r for r in rows if r["regression"]]
    return {
        "a": a,
        "b": b,
        "kernels": {a: kernels[0], b: kernels[1]},
        "rows": rows,
        "only_a": [dict(zip(KEY, k, strict=True)) for k in only_a],
        "only_b": [dict(zip(KEY, k, strict=True)) for k in only_b],
        "regressions": regressions,
        "regression_count": len(regressions),
        "not_complete": bad,
        "problems": {a: problems[0], b: problems[1]},
    }


def summary_line(regressions, bad):
    """'no regressions', '3 regressions, 1 job not Complete'."""
    s = "s" if regressions != 1 else ""
    words = [f"{regressions} regression{s}" if regressions else "no regressions"]
    if bad:
        words.append(f"{len(bad)} job{'s' if len(bad) != 1 else ''} not Complete")
    return ", ".join(words)


def _regression_text(r):
    what = " ".join(r[k] for k in KEY if r[k])
    return f"{what} {r['change_percent']:+.0f} %"


def result_summary(rows, a, b, kernel, jobs, bad, most=3):
    """One line: 'round 20 (v6.12.119-rt25) against 19: 54 jobs, no
    regressions', or the regressions named (the first most)."""
    regs = [r for r in rows if r["regression"]]
    text = f"round {b} ({kernel}) against {a}: {jobs} jobs, "
    text += summary_line(len(regs), [])
    if regs:
        named = ", ".join(_regression_text(r) for r in regs[:most])
        text += " (" + named + (", ..." if len(regs) > most else "") + ")"
    if bad:
        text += f", {len(bad)} job{'s' if len(bad) != 1 else ''} not Complete"
    return text


def compare_url(system_config, a, b):
    """The rounds-compared dashboard of a and b, None without grafana-url."""
    base = str(system_config.get("grafana-url") or "").rstrip("/")
    if not base:
        return None
    return f"{base}/d/{COMPARE_UID}?var-round_a={a}&var-round_b={b}"


def write_result(path, system_config, rows, a, b, kernel, jobs, bad):
    """The result for srt test, as JSON in path."""
    regs = [r for r in rows if r["regression"]]
    result = {
        "status": "fail" if regs or bad else "pass",
        "summary": result_summary(rows, a, b, kernel, jobs, bad),
        "round": str(b),
        "against": str(a),
        "regressions": regs,
        "not_complete": bad,
    }
    url = compare_url(system_config, a, b)
    if url:
        result["url"] = url
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def print_compare(rows, only_a, only_b, a, b, problems, bad, kernels):
    print(f"round {b} ({kernels[1]}) against {a} ({kernels[0]})\n")
    print("\n".join(compare_lines(rows, a, b)))
    for rid, keys in ((a, only_a), (b, only_b)):
        if keys:
            print(f"\nonly in round {rid}:")
            for key in keys:
                print("  " + " ".join(k for k in key if k))
    for rid, lines in ((a, problems[0]), (b, problems[1])):
        if lines:
            print(f"\nproblems in round {rid}:")
            for line in lines:
                print("  " + line)
    if bad:
        print(f"\nnot Complete in round {b}:")
        for line in bad:
            print("  " + line)


def cmd_round_compare(args, system_config, machine_config):
    archive = archive_path(system_config)
    a, b = pick_rounds(archive, getattr(args, "a", None), getattr(args, "b", None))
    min_percent, min_us = thresholds(system_config)
    ra, pa, _ = round_results(archive, a)
    rb, pb, bad = round_results(archive, b)
    rows, only_a, only_b = compare_rows(ra, rb, min_percent, min_us)
    kernels = tuple(load_round(archive, r).get("kernel") or "-" for r in (a, b))
    regressions = sum(r["regression"] for r in rows)
    result = getattr(args, "result", None)
    if result:
        jobs = len(counted_jobs(load_round(archive, b)))
        write_result(result, system_config, rows, a, b, kernels[1], jobs, bad)
    if getattr(args, "json", False):
        print_json(compare_json(rows, only_a, only_b, a, b, (pa, pb), bad, kernels))
    else:
        print_compare(rows, only_a, only_b, a, b, (pa, pb), bad, kernels)
        print(f"\nround {b} against {a}: {summary_line(regressions, bad)} "
              f"(regression: +{min_percent:g} % and +{min_us:g} us)")  # fmt: skip
    if getattr(args, "check", False) and (regressions or bad):
        sys.exit(1)
