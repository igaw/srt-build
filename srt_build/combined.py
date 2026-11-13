"""Combined jobs: a flavor's tests in one boot, in a fixed order.

A release round runs each flavor's tests one after the other in a
single LAVA job (config.yml flavors: <flavor>: combined) instead of
one boot per test: more test time per round, fewer boots, and every
test always runs at the same point after boot, behind the same tests.
Each test stays its own test definition, so LAVA keeps its results in
a suite of its own ("<n>_<name>") and report, export and dashboards
show it as before. The per-test jobs remain for debugging (lava
--split).
"""

import copy

import yaml

from .helpers import convert_to_seconds, generate_job, job_templates

# The job's name and test label: it runs the flavor's rt tests.
JOB_TEST = "rt-tests"

# Before the first test: the end of the boot (systemd, NFS, the
# shell's own setup) is no load to measure under.
SETTLE = "settle"
SETTLE_SECONDS = 30

# Definitions that check or set up around a test, not tests themselves.
_HELPERS = ("kernel-log", "fair-server", "fair-server-on", SETTLE)

# Timeout slack per test for setup, result parsing and uploads.
TEST_SLACK = 120


def entries(flavor_cfg):
    """[(test, duration or None)] from a flavor's combined list.

    An entry is a test (a template's job_name) or {test: duration}.
    """
    out = []
    for e in (flavor_cfg or {}).get("combined") or []:
        if isinstance(e, dict):
            ((name, dur),) = e.items()
            out.append((str(name), str(dur) if dur else None))
        else:
            out.append((str(e), None))
    return out


def render_templates(job_path, testpath, job_ctx):
    """{job_name: parsed job} of every template in testpath."""
    jobs = {}
    for path, ctx in job_templates(testpath, job_ctx):
        j = yaml.safe_load(generate_job(job_path, path, ctx))
        jobs[j["job_name"]] = j
    return jobs


def _settle():
    return {
        "test": {
            "timeout": {"seconds": SETTLE_SECONDS + 60},
            "definitions": [
                {
                    "from": "inline",
                    "name": SETTLE,
                    "path": "inline/settle.yaml",
                    "repository": {
                        "metadata": {
                            "format": "Lava-Test Test Definition 1.0",
                            "name": SETTLE,
                            "description": "let the boot settle before measuring",
                        },
                        # A case, so the definition has a suite of its
                        # own: jobs report flags one without results.
                        "run": {
                            "steps": [
                                f"sleep {SETTLE_SECONDS}",
                                "lava-test-case settle --result pass",
                            ]
                        },
                    },
                }
            ],
        }
    }


def _fair_server_restore():
    """Back to the runtimes job-base.jinja2's fair-server step saved."""
    d = "/sys/kernel/debug/sched/fair_server"
    return {
        "test": {
            "timeout": {"minutes": 1},
            "definitions": [
                {
                    "from": "inline",
                    "name": "fair-server-on",
                    "path": "inline/fair-server-on.yaml",
                    "repository": {
                        "metadata": {
                            "format": "Lava-Test Test Definition 1.0",
                            "name": "fair-server-on",
                            "description": "switch the fair server back on",
                        },
                        "run": {
                            "steps": [
                                f"for f in {d}/cpu*/runtime; do"
                                ' c=$(basename $(dirname "$f"));'
                                ' cat "/tmp/fair-server-$c" > "$f"; done',
                                "lava-test-case fair-server-on --shell"
                                f" '! grep -qx 0 {d}/cpu*/runtime'",
                            ]
                        },
                    },
                }
            ],
        }
    }


def _is_fair_server_off(action):
    return any(d.get("name") == "fair-server" for d in action["test"]["definitions"])


def _main_definition(action):
    for d in action["test"]["definitions"]:
        if d.get("from") == "git":
            return d
    return None


def _unique_names(actions):
    """Make the test definitions' names unique, as LAVA requires.

    Each test brings the template's inline checks (kernel-log after
    every test): a repeated one is renamed after the test it follows,
    "kernel-log-cyclictest", and so is its LAVA suite.
    """
    defs = [d for a in actions if "test" in a for d in a["test"]["definitions"]]
    count = {}
    for d in defs:
        count[d["name"]] = count.get(d["name"], 0) + 1
    last = None
    for d in defs:
        name = d["name"]
        if name not in _HELPERS:
            last = name
            continue
        if count[name] < 2:
            continue
        new = f"{name}-{last}"
        d["name"] = new
        d["path"] = f"inline/{new}.yaml"
        meta = (d.get("repository") or {}).get("metadata")
        if meta:
            meta["name"] = new


def build(rendered, tests, flavor, duration=None):
    """One job running tests [(name, duration)] of rendered in order.

    rendered: {job_name: parsed job} of the flavor's templates;
    duration: seconds, overrides every test's duration (lava
    --duration). Returns the job (a dict).
    """
    missing = [n for n, _ in tests if n != SETTLE and n not in rendered]
    if missing:
        raise ValueError(f"{flavor}: no template for {', '.join(missing)}")
    first = rendered[next(n for n, _ in tests if n != SETTLE)]
    job = copy.deepcopy(first)
    actions = [a for a in job["actions"] if "test" not in a]
    test_seconds = 0
    longest = 0
    for name, dur in tests:
        if name == SETTLE:
            actions.append(_settle())
            test_seconds += SETTLE_SECONDS + 60
            continue
        fair_server_off = False
        for a in rendered[name]["actions"]:
            if "test" not in a:
                continue
            a = copy.deepcopy(a)
            fair_server_off |= _is_fair_server_off(a)
            d = _main_definition(a)
            params = (d or {}).get("parameters") or {}
            if "DURATION" in params:
                if duration:
                    params["DURATION"] = f"{duration}s"
                elif dur:
                    params["DURATION"] = dur
                secs = convert_to_seconds(params["DURATION"])
                a["test"]["timeout"] = {"seconds": secs + TEST_SLACK}
                longest = max(longest, secs)
            to = a["test"].get("timeout") or {"minutes": 5}
            a["test"]["timeout"] = to
            test_seconds += to.get("seconds", 0) + 60 * to.get("minutes", 0)
            actions.append(a)
            if fair_server_off and d is not None:
                actions.append(_fair_server_restore())
                test_seconds += 60
                fair_server_off = False
    _unique_names(actions)
    job["actions"] = actions
    # "rt-tests", with the flavor where the flavor's own jobs name it
    # ("cyclictest rt-isolcpus" -> "rt-tests rt-isolcpus")
    job["job_name"] = " ".join([JOB_TEST] + first["job_name"].split()[1:])
    job["metadata"]["srt.test"] = JOB_TEST
    t = job["timeouts"]
    # The template's job timeout covers deploy and boot (with retries).
    t["job"] = {"minutes": int(t["job"]["minutes"]) + -(-test_seconds // 60)}
    # No console output during a test's measurement: the connection
    # must outlast the longest one.
    quiet = -(-(longest + TEST_SLACK) // 60)
    t["connection"] = {"minutes": max(int(t["connection"]["minutes"]), quiet)}
    t["action"] = {"minutes": max(int(t["action"]["minutes"]), quiet)}
    return job
