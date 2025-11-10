"""Jobs cancel command - cancel LAVA jobs."""
from subprocess import run
from ..helpers import ensure_lavacli_available, get_job_list, get_jobs


def add_parser(subparser):
    """Add jobs cancel command parser."""
    cpsg = subparser.add_parser('cancel')
    cpsg.add_argument('machine', help='Target machine')
    cpsg.add_argument('id', nargs='?')
    cpsg.set_defaults(func=cmd_jobs_cancel)
    return cpsg


def cmd_jobs_cancel(ctx, system_config):
    """Cancel LAVA jobs by ID."""
    ensure_lavacli_available()
    if not ctx.args.id:
        jobs = get_job_list(ctx, system_config)
        id = int(jobs[-1])
    else:
        id = int(ctx.args.id)

    for j in get_jobs(ctx.args.machine, id, system_config, batch=True):
        print(j)
        run(['lavacli', 'jobs', 'cancel', str(j)])
