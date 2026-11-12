"""Helper utilities for LAVA job management and kernel builds."""

import os
import re
import sys
import shutil
import subprocess
import yaml
import jinja2
from logging import error
from .core import run_cmd
from .report import KNOWN_KERNEL_WARNINGS
from .database import (
    save_job_ids_to_db,
    get_jobs_from_db,
    get_job_list_from_db,
)


def ensure_lavacli_available():
    """
    Verify that 'lavacli' is available in PATH.

    Exit with error if not found.
    Required for LAVA-related commands.
    """
    if shutil.which("lavacli") is None:
        from logging import warning

        warning(
            "'lavacli' command not found. "
            "Please install it to use LAVA-related commands.\n"
            "- Via pipx (recommended): pipx install lavacli\n"
            "- Via pip: pip install lavacli\n"
            "Refer to https://docs.lavasoftware.org/lava/lavacli.html"
        )
        sys.exit(1)


class Context:
    """Context object holding machine configuration and arguments."""

    def __init__(self, args, machine_config, system_config):
        # Validate that the machine exists in machine_config
        if args.machine not in machine_config:
            raise KeyError(f'Machine "{args.machine}" not found in machine_config')
        mc = machine_config[args.machine]
        self.__dict__.update(mc)
        self.__dict__["args"] = args
        if args.builddir:
            self.__dict__["build_path"] = args.builddir
        else:
            self.__dict__["build_path"] = (
                system_config["base-build-path"] + "/" + self.hostname
            )
        # Resolve config_path with priority:
        # 1. repository root ./configs
        # 2. package sibling ../configs
        # 3. fallback system_config['base-tool-path']/configs
        repo_configs = os.path.abspath(os.path.join(os.getcwd(), "configs"))
        pkg_configs = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "configs")
        )
        fallback_configs = os.path.abspath(
            os.path.join(system_config["base-tool-path"], "configs")
        )
        if os.path.isdir(repo_configs):
            self.__dict__["config_path"] = repo_configs
        elif os.path.isdir(pkg_configs):
            self.__dict__["config_path"] = pkg_configs
        else:
            self.__dict__["config_path"] = fallback_configs

        # Resolve job_path with same priority ordering as configs
        repo_jobs = os.path.abspath(os.path.join(os.getcwd(), "jobs"))
        pkg_jobs = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "jobs")
        )
        fallback_jobs = os.path.abspath(
            os.path.join(system_config["base-tool-path"], "jobs")
        )
        if os.path.isdir(repo_jobs):
            self.__dict__["job_path"] = repo_jobs
        elif os.path.isdir(pkg_jobs):
            self.__dict__["job_path"] = pkg_jobs
        else:
            self.__dict__["job_path"] = fallback_jobs

    def __getattr__(self, name):
        if name not in self.__dict__:
            return None
        return self.__dict__[name]


def run_make(ctx, cmd):
    """Run make command with proper environment for cross-compilation."""
    ipath = ctx.build_path + "/mods"
    makecmd = ["INSTALL_MOD_PATH=" + ipath, "make", "O=" + ctx.build_path]
    if ctx.LLVM:
        # config --check without the board's cross gcc: clang configures
        # any architecture. Kconfig only asks the linker for its version,
        # so the host ld will do when ld.lld is missing.
        makecmd += ["LLVM=1", "ARCH=" + ctx.ARCH]
        if not shutil.which("ld.lld"):
            makecmd += ["LD=ld"]
    elif ctx.CROSS_COMPILE:
        makecmd += ["CROSS_COMPILE=" + ctx.CROSS_COMPILE]
        makecmd += ["ARCH=" + ctx.ARCH]
    if ctx.CC:
        makecmd += ["CC=" + ctx.CC]
    return run_cmd(makecmd + cmd)


def convert_to_seconds(string):
    """Convert time string (e.g., '5m', '2h', '1d') to seconds."""
    digits = re.compile(r"^\d+")
    value = digits.match(string).group(0)
    postfix = string[len(value) :]
    seconds = int(value)
    if postfix == "d":
        return seconds * 24 * 60 * 60
    if postfix == "h":
        return seconds * 60 * 60
    if postfix == "m":
        return seconds * 60
    return seconds


def load_job_ctx(filename):
    """Load job context from YAML file."""
    job_ctx = {}
    basename = os.path.basename(filename)
    candidates = [
        filename,
        os.path.join(os.getcwd(), basename),
        os.path.join(os.path.dirname(__file__), basename),
        os.path.expanduser(os.path.join("~", ".config", "srt-build", basename)),
    ]

    for path in candidates:
        try:
            if not os.path.exists(path):
                continue
            with open(path, "r") as stream:
                try:
                    job_ctx = yaml.safe_load(stream) or {}
                    return job_ctx
                except yaml.YAMLError as exc:
                    error(f"YAML parse error in job ctx {path}: {exc}")
                    return {}
        except Exception as exc:
            error(f"Error reading job context file {path}: {exc}")
            continue

    error(f"Job context not found; tried: {candidates}")
    return job_ctx


def generate_job(job_path, filename, job_ctx):
    """Generate job file from Jinja2 template."""
    with open(filename, "r") as details:
        data = details.read()
    string_loader = jinja2.DictLoader({filename: data})
    type_loader = jinja2.FileSystemLoader([job_path])
    loader = jinja2.ChoiceLoader([string_loader, type_loader])
    env = jinja2.Environment(loader=loader, trim_blocks=True, autoescape=False)
    job_template = env.get_template(filename)

    return job_template.render(**job_ctx)


def generate_file(job, testname, devicename):
    """Generate a single job file."""
    filename = f"test-{testname}-{devicename}.yaml"
    with open(filename, "w") as f:
        f.write(job)
    return [filename]


def _find_test_index(job):
    """The index of the job's test action, the one running the test
    definition from git: the first test action can be an inline one
    of job-base.jinja2 (fair-server), whose timeout a long test would
    then never get."""
    first = None
    for idx, val in enumerate(job.get("actions", [])):
        if "test" not in val:
            continue
        if first is None:
            first = idx
        defs = val["test"].get("definitions") or []
        if any(d.get("from") == "git" for d in defs):
            return idx
    return first or 0


def _initial_timeout(job, idx):
    """Get initial timeout from job definition."""
    timeout = None
    action_to = job.get("timeouts", {}).get("action")
    if action_to:
        timeout = action_to
    test_to = job.get("actions", [{}])[idx].get("test", {}).get("timeout")
    if test_to:
        timeout = test_to
    return timeout


def _override_duration_and_timeout(t, duration):
    """Override test duration and compute timeout."""
    # returns (new_duration, timeout_dict or None)
    if "parameters" in t and "DURATION" in t["parameters"]:
        if duration:
            t["parameters"]["DURATION"] = f"{duration}s"
        else:
            duration = convert_to_seconds(t["parameters"]["DURATION"])
        return duration, {"seconds": duration + 120}
    return duration, None


def _bump_job_timeouts(job, duration):
    """Make the job timeouts large enough for a test of duration seconds.

    The template's job timeout covers everything but the measurement:
    deploy, boot (with bbb's boot retries) and the kernel-log check. A
    long test adds to it; replacing it with the test time alone left a
    1 h test 19 s short after a boot retry (job 718).
    """
    if duration is None:
        return
    # The test action's own timeout is duration + 120 s.
    test_mins = -(-(int(duration) + 120) // 60)
    try:
        base = int(job["timeouts"]["job"]["minutes"])
        if base * 60 < duration + 120:
            job["timeouts"]["job"]["minutes"] = base + test_mins
        for name in ("action", "connection"):
            if int(job["timeouts"][name]["minutes"]) * 60 < duration:
                job["timeouts"][name]["minutes"] = test_mins
    except Exception:
        # be tolerant if structure changes
        pass


def generate_split_files(td, job, devicename, duration):
    """Split job into multiple files, one per test definition."""
    split_files = []

    job = yaml.safe_load(job)

    idx = _find_test_index(job)
    tests = job["actions"][idx]["test"]["definitions"] or []

    timeout = _initial_timeout(job, idx)
    if duration:
        timeout = {"seconds": duration + 120}

    for t in tests:
        # compute duration/timeout for this test
        duration, t_timeout = _override_duration_and_timeout(t, duration)
        if t_timeout:
            timeout = t_timeout
        _bump_job_timeouts(job, duration)

        action = {"test": {"definitions": [t]}}
        if timeout:
            action["test"]["timeout"] = timeout

        job["actions"][idx] = action

        filename = f'{td}/test-{t["name"]}-{devicename}.yaml'
        with open(filename, "w") as f:
            yaml.dump(job, f, default_flow_style=False)
        split_files.append(filename)

    return split_files


DEFAULT_FLAVORS = ["rt", "rt-isolcpus", "nohz", "vp", "ll", "up", "lazy"]


def flavor_kernel(fl):
    """The flavor whose kernel fl boots: fl itself, or for a flavor like
    rt-isolcpus (config.yml flavors) the one named by its kernel key."""
    from . import config

    return (config.flavors.get(fl) or {}).get("kernel", fl)


def _needs_isolcpus(fl):
    from . import config

    return bool((config.flavors.get(fl) or {}).get("needs_isolcpus"))


def flavor_kernel_args(ctx, fl):
    """Extra kernel arguments for flavor fl on this board.

    The flavor's kernel_args (config.yml flavors) with {isolcpus} and
    {housekeeping} replaced by the board's isolcpus and
    housekeeping_cpus, plus the board's own kernel_args for fl. On a
    board without isolcpus, arguments that need them are left out.
    """
    from . import config

    args = []
    common = (config.flavors.get(fl) or {}).get("kernel_args", "")
    isolcpus = getattr(ctx, "isolcpus", None)
    housekeeping = getattr(ctx, "housekeeping_cpus", None)
    if common and ("{isolcpus}" not in common or isolcpus):
        args.append(common.format(isolcpus=isolcpus, housekeeping=housekeeping or "0"))
    board = (getattr(ctx, "kernel_args", None) or {}).get(fl)
    if board:
        args.append(board)
    return " ".join(args)


def fair_server_off(fl, kernel_describe):
    """The tests of flavor fl whose jobs switch the fair server off on
    this kernel (config.yml flavors: fair_server_off, {git describe
    prefix: [tests]})."""
    from . import config

    releases = (config.flavors.get(fl) or {}).get("fair_server_off") or {}
    return sorted(
        {
            t
            for r, tests in releases.items()
            if kernel_describe.startswith(r)
            for t in tests
        }
    )


def get_flavors(ctx, builds_only=False):
    """Get list of kernel flavors to build or test.

    Flavors listed in the machine's skip_flavors (config.yml) are left
    out, e.g. "up" on arm64, which can't build a uniprocessor kernel, as
    are flavors that need isolated CPUs on a board without them.
    builds_only: only flavors with a kernel of their own (not rt-isolcpus).
    """
    flavors = list(DEFAULT_FLAVORS)
    if getattr(ctx.args, "flavors", None):
        flavors = [f.strip() for f in ctx.args.flavors.split(",") if f.strip()]
    skip = list(getattr(ctx, "skip_flavors", None) or [])
    if not getattr(ctx, "isolcpus", None):
        skip += [f for f in flavors if _needs_isolcpus(f)]
    for f in flavors:
        if f in skip:
            print(f"Skipping flavor {f}: not supported on {ctx.hostname}")
    flavors = [f for f in flavors if f not in skip]
    if builds_only:
        flavors = [f for f in flavors if flavor_kernel(f) == f]
    return flavors


def srt_build_version():
    """srt-build's git commit, "-dirty" with local changes; "unknown"
    outside a checkout. Goes into each job's metadata, so a round shows
    which srt-build version submitted it."""
    global _SRT_BUILD_VERSION
    if _SRT_BUILD_VERSION is None:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            out = subprocess.run(
                ["git", "-C", repo, "describe", "--always", "--dirty", "--abbrev=12"],
                capture_output=True,
                text=True,
                check=True,
            )
            _SRT_BUILD_VERSION = out.stdout.strip() or "unknown"
        except (OSError, subprocess.CalledProcessError):
            _SRT_BUILD_VERSION = "unknown"
    return _SRT_BUILD_VERSION


_SRT_BUILD_VERSION = None


def flavor_job_ctx(ctx, fl, job_ctx):
    """Add what the job templates need to know about flavor fl."""
    job_ctx["board"] = ctx.hostname
    job_ctx["flavor"] = fl
    job_ctx["kernel_describe"] = getattr(ctx, "kernel_describe", "") or ""
    job_ctx["srt_build"] = srt_build_version()
    # Never empty: grep -vE "" would drop every line.
    job_ctx["kernel_log_known"] = "|".join(KNOWN_KERNEL_WARNINGS) or "^$"
    job_ctx["kernel_args"] = flavor_kernel_args(ctx, fl)
    job_ctx["fair_server_off_tests"] = fair_server_off(fl, job_ctx["kernel_describe"])
    isolcpus = getattr(ctx, "isolcpus", None)
    job_ctx["isolcpus"] = isolcpus or ""
    job_ctx["housekeeping_cpus"] = getattr(ctx, "housekeeping_cpus", None) or "0"
    cpus = expand_cpus(isolcpus) if isolcpus else []
    job_ctx["isolcpus_count"] = len(cpus)
    job_ctx["isolcpus_first"] = cpus[0] if cpus else 0
    hk = expand_cpus(job_ctx["housekeeping_cpus"])
    job_ctx["housekeeping_mask"] = sum(1 << c for c in hk)
    return job_ctx


def expand_cpus(cpulist):
    """[1, 2, 3] for "1-3"; also "0,2-3"."""
    cpus = []
    for part in str(cpulist).split(","):
        part = part.strip()
        if not part:
            continue
        first, _, last = part.partition("-")
        cpus += range(int(first), int(last or first) + 1)
    return cpus


def prepare_build_for_flavor(ctx, fl):
    """Prepare build settings for specific flavor."""
    ctx.args.dest = "lava"
    ctx.args.postfix = "-" + fl
    (res, ref) = run_cmd(["git", "describe"])
    if not res:
        ctx.kernel_describe = ref.strip()
        ctx.args.postfix += "-" + ctx.kernel_describe


def get_testpath(ctx, fl):
    """Get path to test suite for flavor."""
    testpath = ctx.job_path + "/" + fl
    if ctx.args.testsuites:
        testpath = testpath + "/" + ctx.args.testsuites
    return testpath


def _submit(path, jobs):
    (_, res) = run_cmd(["lavacli", "jobs", "submit", path])
    jobs.append(str(res).strip())


def combined_tests(ctx, fl):
    """The flavor's tests for one combined job ([] for one job per test).

    Only for the default suite (smoke), and not with --split or --tests.
    """
    from . import config
    from .combined import entries

    if getattr(ctx.args, "split", False) or ctx.args.tests:
        return []
    if (ctx.args.testsuites or "smoke") != "smoke":
        return []
    return entries(config.flavors.get(fl))


def process_test_files(ctx, td, job_ctx, testpath, duration, jobs, fl=None):
    """Process all test template files in testpath."""
    from . import combined

    tests = combined_tests(ctx, fl) if fl else []
    in_combined = {name for name, _ in tests}
    if tests:
        rendered = combined.render_templates(ctx.job_path, testpath, job_ctx)
        job = combined.build(rendered, tests, fl, duration)
        filename = f"{td}/test-combined-{fl}-{ctx.hostname}.yaml"
        with open(filename, "w") as f:
            yaml.dump(job, f, default_flow_style=False)
        _submit(filename, jobs)

    for file in sorted(os.listdir(testpath)):
        if not file.endswith(".jinja2"):
            continue

        filename = testpath + "/" + file
        job = generate_job(ctx.job_path, filename, job_ctx)

        j = yaml.safe_load(job)
        if ctx.args.tests and j["job_name"] != ctx.args.tests:
            continue
        if j["job_name"] in in_combined:
            continue

        files = generate_split_files(td, job, ctx.hostname, duration)
        for j in files:
            _submit(j, jobs)


def save_job_ids(ctx, jobs, system_config):
    """Save job IDs to database for later reference."""
    if jobs == []:
        print("no jobs")
        return

    machine = ctx.args.machine
    save_job_ids_to_db(machine, jobs, system_config)
    print(f"job id: {jobs[0]}")


def get_jobs(machine, job_id, system_config, batch=False):
    """Get list of job IDs from database."""
    return get_jobs_from_db(machine, job_id, system_config, batch)


def get_job_list(ctx, system_config):
    """Get all job IDs for a machine from database."""
    machine = ctx.args.machine
    return get_job_list_from_db(machine, system_config)
