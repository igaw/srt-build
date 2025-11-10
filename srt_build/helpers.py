"""Helper utilities for LAVA job management and kernel builds."""
import os
import re
import sys
import shutil
import yaml
import jinja2
import multiprocessing
from logging import error, debug
from .core import run_cmd


def ensure_lavacli_available():
    """
    Verify that 'lavacli' is available in PATH.
    
    Exit with error if not found.
    Required for LAVA-related commands.
    """
    if shutil.which('lavacli') is None:
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
            raise KeyError(
                f'Machine "{args.machine}" not found in machine_config'
            )
        mc = machine_config[args.machine]
        self.__dict__.update(mc)
        self.__dict__['args'] = args
        if args.builddir:
            self.__dict__['build_path'] = args.builddir
        else:
            self.__dict__['build_path'] = (
                system_config['base-build-path'] + '/' + self.hostname
            )
        self.__dict__['config_path'] = (
            system_config['base-tool-path'] + '/' + 'configs'
        )
        self.__dict__['job_path'] = (
            system_config['base-tool-path'] + '/' + 'jobs'
        )

    def __getattr__(self, name):
        if name not in self.__dict__:
            return None
        return self.__dict__[name]


def run_make(ctx, cmd):
    """Run make command with proper environment for cross-compilation."""
    ipath = ctx.build_path + '/mods'
    makecmd = ['INSTALL_MOD_PATH=' + ipath, 'make', 'O=' + ctx.build_path]
    if ctx.CROSS_COMPILE:
        makecmd += ['CROSS_COMPILE=' + ctx.CROSS_COMPILE]
        makecmd += ['ARCH=' + ctx.ARCH]
    if ctx.CC:
        makecmd += ['CC=' + ctx.CC]
    return run_cmd(makecmd + cmd)


def convert_to_seconds(string):
    """Convert time string (e.g., '5m', '2h', '1d') to seconds."""
    digits = re.compile(r'^\d+')
    value = digits.match(string).group(0)
    postfix = string[len(value):]
    seconds = int(value)
    if postfix == 'd':
        return seconds * 24 * 60 * 60
    if postfix == 'h':
        return seconds * 60 * 60
    if postfix == 'm':
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
        os.path.expanduser(os.path.join('~', '.config', 'srt-build', basename)),
    ]

    for path in candidates:
        try:
            if not os.path.exists(path):
                continue
            with open(path, 'r') as stream:
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
    filename = f'test-{testname}-{devicename}.yaml'
    with open(filename, 'w') as f:
        f.write(job)
    return [filename]


def _find_test_index(job):
    """Find the test action index in job definition."""
    for idx, val in enumerate(job.get('actions', [])):
        if 'test' in val:
            return idx
    return 0


def _initial_timeout(job, idx):
    """Get initial timeout from job definition."""
    timeout = None
    action_to = job.get('timeouts', {}).get('action')
    if action_to:
        timeout = action_to
    test_to = job.get('actions', [{}])[idx].get('test', {}).get('timeout')
    if test_to:
        timeout = test_to
    return timeout


def _override_duration_and_timeout(t, duration):
    """Override test duration and compute timeout."""
    # returns (new_duration, timeout_dict or None)
    if 'parameters' in t and 'DURATION' in t['parameters']:
        if duration:
            t['parameters']['DURATION'] = f'{duration}s'
        else:
            duration = convert_to_seconds(t['parameters']['DURATION'])
        return duration, {'seconds': duration + 120}
    return duration, None


def _bump_job_timeouts(job, duration):
    """Ensure job timeouts are large enough given duration (seconds)."""
    if duration is None:
        return
    mins = int(duration / 60) + 5
    try:
        if int(job['timeouts']['action']['minutes']) * 60 < duration:
            job['timeouts']['action']['minutes'] = mins
        if int(job['timeouts']['job']['minutes']) * 60 < duration:
            job['timeouts']['job']['minutes'] = mins
        if int(job['timeouts']['connection']['minutes']) * 60 < duration:
            job['timeouts']['connection']['minutes'] = mins
    except Exception:
        # be tolerant if structure changes
        pass


def generate_split_files(td, job, devicename, duration):
    """Split job into multiple files, one per test definition."""
    split_files = []

    job = yaml.safe_load(job)

    idx = _find_test_index(job)
    tests = job['actions'][idx]['test']['definitions']

    timeout = _initial_timeout(job, idx)
    if duration:
        timeout = {'seconds': duration + 120}

    for t in tests:
        # compute duration/timeout for this test
        duration, t_timeout = _override_duration_and_timeout(t, duration)
        if t_timeout:
            timeout = t_timeout
        _bump_job_timeouts(job, duration)

        action = {'test': {'definitions': [t]}}
        if timeout:
            action['test']['timeout'] = timeout

        job['actions'][idx] = action

        filename = f'{td}/test-{t["name"]}-{devicename}.yaml'
        with open(filename, 'w') as f:
            yaml.dump(job, f, default_flow_style=False)
        split_files.append(filename)

    return split_files


def get_flavors(ctx):
    """Get list of kernel flavors to build."""
    flavors = ['rt', 'nohz', 'vp', 'll', 'up']
    if ctx.args.flavors:
        flavors = ctx.args.flavors.split(' ,')
    return flavors


def prepare_build_for_flavor(ctx, fl):
    """Prepare build settings for specific flavor."""
    ctx.args.dest = 'lava'
    ctx.args.postfix = '-' + fl
    (res, ref) = run_cmd(['git', 'describe'])
    if not res:
        ctx.args.postfix += '-' + ref.strip()


def get_testpath(ctx, fl):
    """Get path to test suite for flavor."""
    testpath = ctx.job_path + '/' + fl
    if ctx.args.testsuites:
        testpath = testpath + '/' + ctx.args.testsuites
    return testpath


def process_test_files(ctx, td, job_ctx, testpath, duration, jobs):
    """Process all test template files in testpath."""
    for file in sorted(os.listdir(testpath)):
        if not file.endswith('.jinja2'):
            continue

        filename = testpath + '/' + file
        job = generate_job(ctx.job_path, filename, job_ctx)

        j = yaml.safe_load(job)
        if ctx.args.tests and j['job_name'] != ctx.args.tests:
            continue

        files = generate_split_files(td, job, ctx.hostname, duration)
        for j in files:
            (_, res) = run_cmd(['lavacli', 'jobs', 'submit', j])
            jobs.append(str(res).strip())


def save_job_ids(ctx, jobs, system_config):
    """Save job IDs to file for later reference."""
    if jobs == []:
        print('no jobs')
        return
    jobfile = (
        f'{system_config["jobfiles-path"]}/srt-build.{ctx.args.machine}.jobs'
    )
    with open(jobfile, 'a') as f:
        f.write(f'{jobs[0]}: ')
        f.write(' '.join(jobs))
        f.write('\n')
    print(f'job id: {jobs[0]}')


def get_jobs(machine, job_id, system_config, batch=False):
    """Get list of job IDs from saved job file."""
    if not batch:
        return [int(job_id)]

    try:
        jobfile = f'{system_config["jobfiles-path"]}/srt-build.{machine}.jobs'
        with open(jobfile, 'r') as f:
            for line in f.readlines():
                try:
                    id_str = line.split(':')[0]
                    n = int(id_str)
                except Exception as exc:
                    debug(f'Error parsing job id from line: {line} ({exc})')
                    continue
                if id_str and n == job_id:
                    return [
                        int(x.strip())
                        for x in line.split(":")[1].split(' ')
                        if x
                    ]
    except Exception as exc:
        error(f'Error reading jobs file for machine {machine}: {exc}')
    return [int(job_id)]


def get_job_list(ctx, system_config):
    """Get all job IDs for a machine."""
    jobs = []
    try:
        jobfile = (
            f'{system_config["jobfiles-path"]}/srt-build.{ctx.args.machine}.jobs'
        )
        with open(jobfile, 'r') as f:
            for line in f.readlines():
                try:
                    id = int(line.split(':')[0])
                except Exception as exc:
                    debug(f'Error parsing job id from line: {line} ({exc})')
                    continue
                jobs.append(id)
    except Exception as exc:
        error(f'Error reading jobs file for machine {ctx.args.machine}: {exc}')
    return jobs
