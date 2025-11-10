"""Jobs compare command - compare results between two LAVA jobs."""


def add_parser(subparser):
    """Add jobs compare command parser."""
    kpsg = subparser.add_parser('compare')
    kpsg.add_argument('machine', help='Target machine')
    kpsg.add_argument('id1', nargs='?')
    kpsg.add_argument('id2', nargs='?')
    kpsg.set_defaults(func=cmd_jobs_compare)
    return kpsg


def cmd_jobs_compare(ctx):
    """Compare results between two job IDs."""
    # Import necessary functions from main module when refactored
    # ensure_lavacli_available, get_results, lookup_entry, etc.
    pass
