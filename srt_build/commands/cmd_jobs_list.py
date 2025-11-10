"""Jobs list command - list all LAVA job IDs."""


def add_parser(subparser):
    """Add jobs list command parser."""
    lpsg = subparser.add_parser('list')
    lpsg.add_argument('machine', help='Target machine')
    lpsg.set_defaults(func=cmd_jobs_list)
    return lpsg


def cmd_jobs_list(ctx):
    """List all job IDs for the specified machine."""
    # Import get_job_list from main module when refactored
    # for id in get_job_list(ctx):
    #     print(id)
    pass
