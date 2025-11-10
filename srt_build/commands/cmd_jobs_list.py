"""Jobs list command - list all LAVA job IDs."""
from ..helpers import get_job_list


def add_parser(subparser):
    """Add jobs list command parser."""
    lpsg = subparser.add_parser('list')
    lpsg.add_argument('machine', help='Target machine')
    lpsg.set_defaults(func=cmd_jobs_list)
    return lpsg


def cmd_jobs_list(ctx, system_config):
    """List all job IDs for the specified machine."""
    for id in get_job_list(ctx, system_config):
        print(id)
