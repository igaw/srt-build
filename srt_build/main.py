#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-only
"""Main entry point for srt-build tool."""

import argparse
import sys
import logging

from .config import load_config
from .core import setup
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
    parser = argparse.ArgumentParser(
        description='srt - stable -rt tooling'
    )
    parser.add_argument(
        '-d', '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    parser.add_argument('--append', default='')
    parser.add_argument('--builddir', default=None)

    subparser = parser.add_subparsers(
        help='sub command help',
        dest='cmd',
        required=True
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
    system_config, kernel_config, machine_config, rt_suites, suites = (
        load_config()
    )

    # Setup logging and event loop
    setup(system_config)

    # Parse arguments
    parser = create_parser()
    args = parser.parse_args(sys.argv[1:])

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate machine configuration
    if hasattr(args, 'machine') and args.machine not in machine_config:
        from logging import error
        error(f'No valid machine config found for "{args.machine}"')
        sys.exit(1)

    # Create context and run command
    if hasattr(args, 'machine'):
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
        elif hasattr(args, 'jobs_cmd'):
            # Jobs subcommands
            from .commands import (
                cmd_jobs_list, cmd_jobs_results,
                cmd_jobs_compare, cmd_jobs_cancel
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
    main()
