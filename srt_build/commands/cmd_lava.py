"""Lava command - run LAVA tests with different kernel flavors."""
import tempfile
from shutil import copytree
from ..helpers import (
    ensure_lavacli_available,
    get_flavors,
    convert_to_seconds,
    prepare_build_for_flavor,
    load_job_ctx,
    get_testpath,
    process_test_files,
    save_job_ids,
)
from .cmd_config import cmd_config
from .cmd_build import cmd_build
from .cmd_install import cmd_install


def add_parser(subparser):
    """Add lava command parser."""
    lpsg = subparser.add_parser('lava')
    lpsg.add_argument('machine', help='Target machine')
    lpsg.add_argument('--skip-build', default=False, action='store_true')
    lpsg.add_argument('--mods', default=False, action='store_true')
    lpsg.add_argument('--duration', default=None)
    lpsg.add_argument('--config-base', default='')
    lpsg.add_argument('--tests')
    lpsg.add_argument('--flavors')
    lpsg.add_argument('--testsuites', default='smoke')
    lpsg.set_defaults(func=cmd_lava)
    return lpsg


def build_flavor(ctx, fl, kernel_config):
    """Build a specific flavor if not skipped."""
    if not ctx.args.skip_build:
        ctx.args.flavor = fl
        cmd_config(ctx, kernel_config)
        cmd_build(ctx)
        cmd_install(ctx)


def cmd_lava(ctx, system_config, kernel_config):
    """Run LAVA tests with kernel builds for different flavors."""
    ensure_lavacli_available()
    ctx.args.config = ''

    flavors = get_flavors(ctx)
    duration = None
    if ctx.args.duration:
        duration = convert_to_seconds(ctx.args.duration)

    jobs = []

    for fl in flavors:
        prepare_build_for_flavor(ctx, fl)
        build_flavor(ctx, fl, kernel_config)

        with tempfile.TemporaryDirectory() as td:
            job_ctx = load_job_ctx(
                ctx.job_path + '/boards/' + ctx.hostname + '.yaml'
            )
            job_ctx['kernel_url'] += ctx.args.postfix
            job_ctx['tags'] = [ctx.hostname]

            testpath = get_testpath(ctx, fl)
            process_test_files(ctx, td, job_ctx, testpath, duration, jobs)

            copytree(td, system_config['jobfiles-path'], dirs_exist_ok=True)

    save_job_ids(ctx, jobs, system_config)
