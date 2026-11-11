"""report: job summaries from LAVA data, without a LAVA server.

The cases are the problems seen in real runs: a test script crashing
after the measurement (osnoise parser, job "Complete" but no results),
a failed upload, a failed power-off, a kernel warning on the console.
"""

import json

from srt_build.report import (
    _id_ranges,
    console_lines,
    format_report,
    parse_id_list,
    parse_log,
    scan_console,
    summarize_job,
    summary_line,
)

LAVA, OSNOISE = 1, 2
SUITES = [{"id": LAVA, "name": "lava"}, {"id": OSNOISE, "name": "0_rtla-osnoise"}]


def job(jid=44, health="Complete", state="Finished"):
    return {
        "id": jid,
        "actual_device": "rpi3-32",
        "description": "rtla-osnoise",
        "state": state,
        "health": health,
    }


def case(name, result="pass", suite=OSNOISE, measurement=None, unit="", md=""):
    return {
        "name": name,
        "result": result,
        "suite": suite,
        "measurement": measurement,
        "unit": unit,
        "metadata": md,
    }


def log(*entries):
    return "\n".join("- " + json.dumps(e) for e in entries) + "\n"


def target(msg):
    return {"dt": "2026-11-09T22:17:11", "lvl": "target", "msg": msg}


def test_parse_log_json_and_yaml_lines():
    text = (
        '- {"dt": "x", "lvl": "info", "msg": "start"}\n'
        "- {dt: y, lvl: target, msg: 'Linux version 6.12.116-rt22 (gcc)'}\n"
        "not a log line\n"
    )
    entries = parse_log(text)
    assert [e["lvl"] for e in entries] == ["info", "target"]
    assert console_lines(entries) == ["Linux version 6.12.116-rt22 (gcc)"]


def test_console_lines_skip_lava_messages_and_dicts():
    entries = [
        {"lvl": "debug", "msg": "lava's own"},
        {"lvl": "target", "msg": {"not": "text"}},
        {"lvl": "feedback", "msg": "[ 1.0] kernel"},
    ]
    assert console_lines(entries) == ["[ 1.0] kernel"]


def test_scan_console_normalizes_and_dedups():
    lines = [
        "WARNING: CPU: 0 PID: 1 at kernel/foo.c:12 bar+0x1/0x2",
        "WARNING: CPU: 3 PID: 77 at kernel/foo.c:12 bar+0x1/0x2",
        "ValueError: invalid literal for int() with base 10: '3.99'",
        "all fine",
    ]
    assert scan_console(lines) == [
        ("kernel", "WARNING: at kernel/foo.c:12 bar+0x1/0x2"),
        ("test", "ValueError: invalid literal for int() with base 10: '3.99'"),
    ]


def test_crashed_parser_reported_although_complete():
    tests = [
        case("0_rtla-osnoise", suite=LAVA),
        case("job", suite=LAVA),
        case("test-attachment", "fail"),
        case("test-attachment"),
    ]
    text = log(
        target("Linux version 6.12.116-rt22 (gcc 15)"),
        target("Traceback (most recent call last):"),
        target("ValueError: invalid literal for int() with base 10: '3.99'"),
    )
    s = summarize_job(job(), tests, SUITES, text)
    assert s.kernel == "6.12.116-rt22"
    assert s.no_results == ["rtla-osnoise"]
    assert (s.uploads, s.uploads_failed) == (2, 1)
    assert s.problems() == [
        "1 of 2 uploads failed",
        "no results: rtla-osnoise",
        "2 console findings",
    ]


def test_clean_job_has_no_problems():
    tests = [
        case("0_rtla-osnoise", suite=LAVA),
        case("job", suite=LAVA),
        case("t0-max-latency", measurement="12.0000000000", unit="us"),
        case("t1-max-latency", measurement="30.0000000000", unit="us"),
        case("test-attachment"),
    ]
    s = summarize_job(job(), tests, SUITES, log(target("login:")))
    assert s.max_latency == 30.0
    assert s.no_results == []
    assert s.problems() == []


def test_failed_case_and_incomplete_job():
    md = "case: job\nerror_msg: 'Unable to resolve pikvm.lan'\nresult: fail\n"
    tests = [
        case("power-off", "fail", suite=LAVA),
        case("job", "fail", suite=LAVA, md=md),
    ]
    s = summarize_job(job(health="Incomplete"), tests)
    assert s.failed == ["power-off"]
    assert s.error == "Unable to resolve pikvm.lan"
    assert s.problems() == [
        "Incomplete: Unable to resolve pikvm.lan",
        "failed: power-off",
    ]


def test_retried_boot_is_no_problem():
    """bbb boots with failure_retry (U-Boot sometimes misses the PHY):
    the failed attempt's cases stay, next to the passing ones."""
    tests = [
        case("uboot-action", "fail", suite=LAVA),
        case("bootloader-commands", "fail", suite=LAVA),
        case("uboot-action", suite=LAVA),
        case("bootloader-commands", suite=LAVA),
        case("t0-max-latency", measurement="99", unit="us"),
    ]
    s = summarize_job(job(), tests)
    assert s.failed == []
    assert s.retried == ["bootloader-commands", "uboot-action"]
    assert s.problems() == []
    assert "retried: bootloader-commands, uboot-action" in format_report([s])


def test_unfinished_job_is_no_problem():
    s = summarize_job(job(health="Unknown", state="Running"), [])
    assert s.problems() == []


def test_format_report():
    ok = summarize_job(job(1), [case("t0-max-latency", measurement="9", unit="us")])
    bad = summarize_job(job(2, health="Incomplete"), [])
    bad.findings = [("kernel", "BUG: scheduling while atomic")]
    text = format_report([ok, bad])
    assert "rpi3-32" in text
    assert "[kernel] BUG: scheduling while atomic  (jobs 2)" in text
    assert text.endswith("2 jobs, 1 Complete, 1 Incomplete, problems in jobs 2")


def test_summary_line_counts_unfinished():
    jobs = [
        summarize_job(job(1), []),
        summarize_job(job(2, health="Unknown", state="Submitted"), []),
    ]
    assert summary_line(jobs) == "2 jobs, 1 Complete, 1 not finished, no problems"


def test_id_lists():
    assert parse_id_list("13-15, 20,") == [13, 14, 15, 20]
    assert _id_ranges([9, 5, 6, 7, 11, 12]) == "5-7, 9, 11-12"


def test_known_kernel_warning_is_no_finding():
    from srt_build.report import scan_console

    lines = [
        "[    0.000000] WARNING: CPU: 0 PID: 0 at arch/arm/kernel/devtree.c:129 "
        "arm_dt_init_cpu_maps+0xd0/0x15c",
        "[   43.947336] rcu: INFO: rcu_preempt self-detected stall on CPU",
    ]
    assert scan_console(lines) == [
        ("kernel", "rcu: INFO: rcu_preempt self-detected stall on CPU")
    ]
