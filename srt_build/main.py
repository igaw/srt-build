#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-only
"""Main entry point for srt-build tool."""

import argparse
import sys
import logging
import asyncio

from .config import load_config, bcolors
from .core import setup, check_kernel_source_directory
from .helpers import Context
from .commands import (
    cmd_config,
    cmd_build,
    cmd_install,
    cmd_lava,
    cmd_smoke,
    cmd_jobs,
    cmd_kexec,
    cmd_all,
)


def create_parser():
    """Create the main argument parser with all subcommands."""
    parser = argparse.ArgumentParser(description="srt - stable -rt tooling")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug logging"
    )
    parser.add_argument("--append", default="")
    parser.add_argument("--builddir", default=None)

    subparser = parser.add_subparsers(
        help="sub command help", dest="cmd", required=True
    )

    # Add all subcommand parsers
    cmd_config.add_parser(subparser)
    cmd_build.add_parser(subparser)
    cmd_install.add_parser(subparser)
    cmd_lava.add_parser(subparser)
    cmd_smoke.add_parser(subparser)
    cmd_jobs.add_parser(subparser)
    cmd_kexec.add_parser(subparser)
    cmd_all.add_parser(subparser)

    return parser


def main():
    """Main entry point."""
    # Load configuration
    system_config, kernel_config, machine_config, rt_suites, suites = load_config()

    # Parse arguments first to determine which command
    parser = create_parser()
    args = parser.parse_args(sys.argv[1:])

    # Test hook: allow tests to inject a short sleep window to reliably send SIGINT
    # (Used by tests/test_ctrl_c.py). This keeps production behavior unchanged.
    import os  # local import to avoid polluting module namespace unnecessarily
    import time
    import contextlib

    _sleep = os.getenv("SRT_BUILD_TEST_SLEEP")
    if _sleep:
        with contextlib.suppress(Exception):
            time.sleep(float(_sleep))

    # Determine if kernel source directory is required for this invocation
    kernel_commands = [
        cmd_build.cmd_build,
        cmd_install.cmd_install,
        cmd_lava.cmd_lava,
        cmd_smoke.cmd_smoke,
        cmd_kexec.cmd_kexec,
        cmd_all.cmd_all,
    ]
    need_kernel_source = (args.func in kernel_commands) or (
        args.func == cmd_config.cmd_config and not getattr(args, "list", False)
    )
    # Exceptions: lava --list-tests and --show-jobs don't need kernel source
    if args.func == cmd_lava.cmd_lava:
        if (hasattr(args, "list_tests") and args.list_tests) or (
            hasattr(args, "show_jobs") and args.show_jobs
        ):
            need_kernel_source = False

    if need_kernel_source:
        check_kernel_source_directory()

    # Setup logging and event loop
    setup(system_config)

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Special handling for lava --list-tests (doesn't require machine)
    if (
        args.func == cmd_lava.cmd_lava
        and hasattr(args, "list_tests")
        and args.list_tests
    ):
        # Create a minimal context without machine validation
        # Use a dummy machine to get job_path
        dummy_machine = list(machine_config.keys())[0]
        args_copy = argparse.Namespace(**vars(args))
        args_copy.machine = dummy_machine
        ctx = Context(args_copy, machine_config, system_config)
        ctx.args = args  # Restore original args
        cmd_lava.cmd_lava(ctx, system_config, kernel_config)
        return

    # Special handling for lava --show-jobs (requires machine but not kernel)
    if args.func == cmd_lava.cmd_lava and hasattr(args, "show_jobs") and args.show_jobs:
        # Machine is required for --show-jobs
        if not args.machine:
            print("Error: machine argument is required for --show-jobs")
            sys.exit(1)
        # Validate machine exists
        if args.machine not in machine_config:
            from logging import error

            error(f'No valid machine config found for "{args.machine}"')
            sys.exit(1)
        # Create context and run
        ctx = Context(args, machine_config, system_config)
        cmd_lava.cmd_lava(ctx, system_config, kernel_config)
        return

    # Validate machine configuration
    if hasattr(args, "machine") and args.machine not in machine_config:
        from logging import error

        error(f'No valid machine config found for "{args.machine}"')
        sys.exit(1)

    # Create context and run command
    if hasattr(args, "machine"):
        ctx = Context(args, machine_config, system_config)
        # Pass necessary config to commands that need it
        if args.func == cmd_config.cmd_config:
            args.func(ctx, kernel_config)
        elif args.func == cmd_lava.cmd_lava:
            args.func(ctx, system_config, kernel_config)
        elif args.func == cmd_smoke.cmd_smoke:
            args.func(ctx, system_config)
        elif args.func == cmd_all.cmd_all:
            args.func(ctx, kernel_config)
        elif hasattr(args, "jobs_cmd"):
            # Jobs subcommands
            from .commands import (
                cmd_jobs_list,
                cmd_jobs_results,
                cmd_jobs_compare,
                cmd_jobs_cancel,
            )

            if args.func == cmd_jobs_list.cmd_jobs_list:
                args.func(ctx, system_config)
            elif args.func == cmd_jobs_results.cmd_jobs_results:
                args.func(ctx, system_config, rt_suites, suites)
            elif args.func == cmd_jobs_compare.cmd_jobs_compare:
                args.func(ctx, system_config, rt_suites, suites)
            elif args.func == cmd_jobs_cancel.cmd_jobs_cancel:
                args.func(ctx, system_config)
            else:
                args.func(ctx)
        else:
            args.func(ctx)
    else:
        # Some commands might not need machine
        args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Graceful Ctrl-C handling
        print(
            f"{bcolors.WARNING}Interrupted by user (Ctrl-C). Exiting cleanly.{bcolors.ENDC}"
        )
        # Use 130 (128 + SIGINT) as conventional exit code for Ctrl-C
        sys.exit(130)
    except asyncio.CancelledError:
        print(f"{bcolors.WARNING}Operation cancelled. Exiting cleanly.{bcolors.ENDC}")
        sys.exit(130)
