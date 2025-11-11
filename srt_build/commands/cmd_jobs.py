"""Jobs command - parent command for job-related operations."""


def add_parser(subparser):
    """Add jobs command parser with subcommands."""
    from . import cmd_jobs_list, cmd_jobs_results, cmd_jobs_compare, cmd_jobs_cancel

    jpsg = subparser.add_parser("jobs")
    sjpsg = jpsg.add_subparsers(
        help="LAVA jobs commands", dest="jobs_cmd", required=True
    )

    # Add subcommands
    cmd_jobs_list.add_parser(sjpsg)
    cmd_jobs_results.add_parser(sjpsg)
    cmd_jobs_compare.add_parser(sjpsg)
    cmd_jobs_cancel.add_parser(sjpsg)

    jpsg.set_defaults(func=cmd_jobs)
    return jpsg


def cmd_jobs(ctx):
    """Parent command for jobs operations."""
    print(ctx.args)
