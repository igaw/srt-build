"""Result handling utilities for LAVA test results."""

import os
import json
import yaml
import urllib.request
from logging import debug, error
from pprint import pprint, pformat
from .config import bcolors
from .core import run_cmd
from .helpers import load_job_ctx


def handle_rt_results(test, job_ctx, rt_suites):
    """Handle RT-specific test results with latency checking."""
    try:
        measurement = float(test["measurement"])
    except Exception as exc:
        debug(f"Could not parse measurement: {exc}")
        measurement = 0.0

    max_latency = -1
    name = test["suite"].split("_")[-1]
    name = name.replace("-", "_")
    if job_ctx and name in job_ctx:
        if job_ctx[name] and "max_latency" in job_ctx[name]:
            max_latency = int(job_ctx[name]["max_latency"])

    if test["result"] == "pass":
        passed = True
    else:
        passed = False

    if test["name"].endswith("max-latency") and measurement >= max_latency:
        passed = False

    if passed:
        result = bcolors.OKGREEN + "pass" + bcolors.ENDC
    else:
        result = bcolors.FAIL + "fail" + bcolors.ENDC
    print(
        f'  {test["job"]:5} {test["suite"]:20} {test["name"]:20}: '
        f"{result} {measurement:>10.2f}"
    )


def get_color_result(passed):
    """Return colored result string based on pass/fail status."""
    if passed:
        return bcolors.OKGREEN + "pass" + bcolors.ENDC
    else:
        return bcolors.FAIL + "fail" + bcolors.ENDC


def handle_result_fail(test, job_ctx):
    """Default handler for failed test results."""
    print(
        f'  {test.get("job", ""):5} {test.get("suite", ""):20} '
        f'{test.get("name", ""):20}: '
        f"{bcolors.FAIL}fail{bcolors.ENDC}"
    )


def handle_default_results(test, job_ctx):
    """Default handler for test results."""
    try:
        measurement = float(test.get("measurement", 0.0))
    except Exception as exc:
        debug(f"Could not parse measurement: {exc}")
        measurement = 0.0

    passed = test.get("result", "") == "pass"
    result = get_color_result(passed)
    print(
        f'  {test.get("job", ""):5} {test.get("suite", ""):20} '
        f'{test.get("name", ""):20}: '
        f"{result} {measurement:>10.2f}"
    )


def print_test_result(test, job_ctx, rt_suites, suites):
    """Print a single test result with appropriate formatting."""
    if test["suite"] in rt_suites:
        handle_rt_results(test, job_ctx, rt_suites)
    elif test["suite"] in suites:
        handle_default_results(test, job_ctx)
    elif test["result"] == "fail":
        handle_result_fail(test, job_ctx)


def job_result_print(
    jobid, job_ctx, metadata, result, system_config, rt_suites, suites, download=False
):
    """Print job results in a formatted manner."""
    if not result:
        print(f"   {jobid:5} no results")
        return

    try:
        res_ctx = yaml.safe_load(result)
    except yaml.YAMLError as exc:
        pprint(exc)
        return

    for test in res_ctx:
        debug(pformat(test))
        print_test_result(test, job_ctx, rt_suites, suites)

        if test["name"] == "test-attachment":
            if "reference" not in test["metadata"]:
                continue
            if download:
                url = test["metadata"]["reference"]

                data = None
                with urllib.request.urlopen(url) as f:
                    data = f.read().decode("utf-8")

                d = json.loads(data)
                fname = os.path.join(
                    system_config["result-path"],
                    metadata["host"],
                    d["sysinfo"]["release"],
                    test["suite"][2:],
                    str(test["job"]),
                    f'{test["suite"][2:]}.json',
                )
                os.makedirs(os.path.dirname(fname), exist_ok=True)
                print(f'  {test["job"]:5} {fname}')
                with open(fname, "w") as outfile:
                    outfile.write(data)


def get_job_context(id, ctx):
    """Get job context including host and description."""
    data = {}
    try:
        (_, res) = run_cmd(["lavacli", "jobs", "show", "--yaml", str(id)])
        job = yaml.safe_load(res)

        # Check if job has a device assigned yet
        if job["device"] is None:
            error(
                f"Job {id} has not been assigned to a device yet "
                f'(state: {job.get("state", "unknown")})'
            )
            return (None, None)

        host = job["device"].split("-")[0]
        data["host"] = host
        data["description"] = job["description"]
        job_ctx = load_job_ctx(ctx.job_path + "/boards/" + host + ".yaml")
        return (data, job_ctx)
    except Exception as exc:
        error(f"Error getting job context for job {id}: {exc}")
        return (None, None)


def get_result(jobid, result, rt_suites, suites):
    """Parse job result into table format."""
    try:
        job_ctx = yaml.safe_load(result)
    except yaml.YAMLError as exc:
        error(f"YAML error in job result for job {jobid}: {exc}")
        return []
    except Exception as exc:
        error(f"Error loading job result for job {jobid}: {exc}")
        return []

    table = []
    for test in job_ctx:
        debug(pformat(test))
        if test["suite"] not in rt_suites and test["suite"] not in suites:
            continue

        try:
            measurement = float(test["measurement"])
        except Exception as exc:
            debug(f"Could not parse measurement: {exc}")
            measurement = 0.0

        table.append([test["suite"], test["name"], test["result"], measurement])

    return table


def get_results(machine, id, system_config, rt_suites, suites):
    """Get results for all jobs in a batch."""
    from .helpers import get_jobs

    results = []
    for j in get_jobs(machine, id, system_config, batch=False):
        (_, res) = run_cmd(["lavacli", "results", "--yaml", str(j)])
        results.extend(get_result(j, res, rt_suites, suites))
    return results


def lookup_entry(table, suite, name):
    """Look up an entry in the results table."""
    for e in table:
        if e[0] == suite and e[1] == name:
            return e
    return None
