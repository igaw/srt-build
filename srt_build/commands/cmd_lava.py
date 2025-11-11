"""Lava command - run LAVA tests with different kernel flavors."""
import os
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
    generate_job,
)
from .cmd_config import cmd_config
from .cmd_build import cmd_build
from .cmd_install import cmd_install


def add_parser(subparser):
    """Add lava command parser."""
    lpsg = subparser.add_parser('lava')
    lpsg.add_argument('machine', nargs='?', help='Target machine')
    lpsg.add_argument('--skip-build', default=False, action='store_true')
    lpsg.add_argument('--mods', default=False, action='store_true')
    lpsg.add_argument('--duration', default=None)
    lpsg.add_argument('--config-base', default='')
    lpsg.add_argument('--tests')
    lpsg.add_argument('--flavors')
    lpsg.add_argument('--testsuites', default='smoke')
    lpsg.add_argument(
        '--list-tests',
        default=False,
        action='store_true',
        help='List all available test suites and tests'
    )
    lpsg.add_argument(
        '--show-jobs',
        default=False,
        action='store_true',
        help='Generate and display job definitions for test suite'
    )
    lpsg.set_defaults(func=cmd_lava)
    return lpsg


def build_flavor(ctx, fl, kernel_config):
    """Build a specific flavor if not skipped."""
    if not ctx.args.skip_build:
        ctx.args.flavor = fl
        cmd_config(ctx, kernel_config)
        cmd_build(ctx)
        cmd_install(ctx)


def extract_test_name(test_path, test_file):
    """Extract test name from template file."""
    try:
        with open(test_path, 'r') as f:
            content = f.read()
            for line in content.split('\n'):
                if 'job_name' in line and '=' in line:
                    # Extract the value after '='
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        value = parts[1].strip()
                        # Remove Jinja2 closing tag if present
                        if '%}' in value:
                            value = value.split('%}')[0].strip()
                        # Remove quotes (both single and double)
                        value = value.strip("'\"")
                        return value
    except Exception:
        pass
    # Fallback to filename
    return test_file.replace('.jinja2', '')


def list_tests_for_suite(item_path, testsuite):
    """List all tests in a test suite."""
    print(f"  Test Suite: {testsuite}")

    try:
        test_files = sorted([
            f for f in os.listdir(item_path)
            if f.endswith('.jinja2')
        ])
    except OSError:
        return

    for test_file in test_files:
        test_path = os.path.join(item_path, test_file)
        name = extract_test_name(test_path, test_file)
        print(f"    - {name}")


def list_available_tests(ctx):
    """List all available test suites and tests."""
    job_path = ctx.job_path
    flavors = ['rt', 'nohz', 'vp', 'll', 'up', 'none']

    if ctx.args.flavors:
        flavors = ctx.args.flavors.split(',')

    print("\nAvailable Test Suites and Tests:")
    print("=" * 80)

    for flavor in flavors:
        flavor_path = os.path.join(job_path, flavor)
        if not os.path.exists(flavor_path):
            continue

        print(f"\n{flavor.upper()} Flavor:")
        print("-" * 80)

        try:
            items = sorted(os.listdir(flavor_path))
        except OSError:
            continue

        for item in items:
            item_path = os.path.join(flavor_path, item)
            if not os.path.isdir(item_path):
                continue

            # Filter by testsuite if specified
            if ctx.args.testsuites and ctx.args.testsuites != item:
                continue

            list_tests_for_suite(item_path, item)

    print("\n" + "=" * 80)
    print("\nUsage examples:")
    print("  # Run smoke tests for rt flavor:")
    print("  ./srt-build-new lava <machine> --flavors rt "
          "--testsuites smoke")
    print("\n  # Run specific test:")
    print("  ./srt-build-new lava <machine> --flavors rt "
          "--tests cyclictest")
    print()


def show_generated_jobs(ctx):
    """Generate and display job definitions for a test suite."""
    # Require machine for job generation
    if not ctx.args.machine:
        print("Error: machine argument is required for --show-jobs")
        print("Usage: ./srt-build-new lava <machine> --show-jobs "
              "[--flavors FLAVOR] [--testsuites SUITE]")
        return

    job_path = ctx.job_path
    flavors = ['rt'] if not ctx.args.flavors else ctx.args.flavors.split(',')

    print("\nGenerating Job Definitions:")
    print("=" * 80)
    print(f"Machine: {ctx.args.machine} ({ctx.hostname})")
    print(f"Flavors: {', '.join(flavors)}")
    print(f"Test Suites: {ctx.args.testsuites}")
    print("=" * 80)

    # Load job context for the machine
    try:
        job_ctx = load_job_ctx(
            ctx.job_path + '/boards/' + ctx.hostname + '.yaml'
        )
        job_ctx['tags'] = [ctx.hostname]
    except Exception as e:
        print(f"\nError loading job context: {e}")
        return

    total_jobs = 0

    for flavor in flavors:
        testpath = os.path.join(job_path, flavor)
        if ctx.args.testsuites:
            testpath = os.path.join(testpath, ctx.args.testsuites)

        if not os.path.exists(testpath):
            print(f"\nWarning: Test path does not exist: {testpath}")
            continue

        print(f"\n{flavor.upper()} Flavor - {ctx.args.testsuites}:")
        print("-" * 80)

        try:
            test_files = sorted([
                f for f in os.listdir(testpath)
                if f.endswith('.jinja2')
            ])
        except OSError as e:
            print(f"Error reading test directory: {e}")
            continue

        for test_file in test_files:
            test_path = os.path.join(testpath, test_file)
            test_name = extract_test_name(test_path, test_file)

            # Filter by specific test if requested
            if ctx.args.tests:
                # Load and parse to get actual job_name
                try:
                    job_yaml = generate_job(ctx.job_path, test_path, job_ctx)
                    import yaml
                    job_data = yaml.safe_load(job_yaml)
                    if job_data.get('job_name') != ctx.args.tests:
                        continue
                except Exception:
                    if test_name != ctx.args.tests:
                        continue

            print(f"\n--- Job: {test_name} ---")
            print(f"Template: {test_file}")

            try:
                # Generate the job
                job_yaml = generate_job(ctx.job_path, test_path, job_ctx)
                print("\nGenerated Job Definition:")
                print("-" * 40)
                print(job_yaml)
                print("-" * 40)
                total_jobs += 1
            except Exception as e:
                print(f"Error generating job: {e}")
                continue

    print("\n" + "=" * 80)
    print(f"Total jobs generated: {total_jobs}")
    print()



def cmd_lava(ctx, system_config, kernel_config):
    """Run LAVA tests with kernel builds for different flavors."""
    # Handle --list-tests flag
    if hasattr(ctx.args, 'list_tests') and ctx.args.list_tests:
        list_available_tests(ctx)
        return

    # Handle --show-jobs flag
    if hasattr(ctx.args, 'show_jobs') and ctx.args.show_jobs:
        show_generated_jobs(ctx)
        return

    # Validate machine argument is provided for normal operation
    if not ctx.args.machine:
        print("Error: machine argument is required")
        print("Use --list-tests to see available tests")
        return

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
