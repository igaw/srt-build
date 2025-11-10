"""Lava command - run LAVA tests with different kernel flavors."""
import tempfile
from shutil import copytree


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


def cmd_lava(ctx):
    """Run LAVA tests with kernel builds for different flavors."""
    # Import these from the main module when refactored
    # ensure_lavacli_available, _get_flavors, convert_to_seconds, etc.
    
    # ensure_lavacli_available()
    ctx.args.config = ''

    flavors = _get_flavors(ctx)
    duration = None
    if ctx.args.duration:
        duration = convert_to_seconds(ctx.args.duration)

    jobs = []

    for fl in flavors:
        _prepare_build_for_flavor(ctx, fl)
        _build_flavor(ctx, fl)

        with tempfile.TemporaryDirectory() as td:
            job_ctx = load_job_ctx(ctx.job_path + '/boards/' + ctx.hostname + '.yaml')
            job_ctx['kernel_url'] += ctx.args.postfix
            job_ctx['tags'] = [ ctx.hostname ]

            testpath = _get_testpath(ctx, fl)
            _process_test_files(ctx, td, job_ctx, testpath, duration, jobs)

            copytree(td, system_config['jobfiles-path'], dirs_exist_ok=True)

    _save_job_ids(ctx, jobs)
