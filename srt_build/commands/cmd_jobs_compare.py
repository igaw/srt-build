"""Jobs compare command - compare results between two LAVA jobs."""
from ..helpers import ensure_lavacli_available
from ..results import get_results, lookup_entry


def add_parser(subparser):
    """Add jobs compare command parser."""
    kpsg = subparser.add_parser('compare')
    kpsg.add_argument('machine', help='Target machine')
    kpsg.add_argument('id1', nargs='?')
    kpsg.add_argument('id2', nargs='?')
    kpsg.set_defaults(func=cmd_jobs_compare)
    return kpsg


def cmd_jobs_compare(ctx, system_config, rt_suites, suites):
    """Compare results between two job IDs."""
    ensure_lavacli_available()
    id1 = int(ctx.args.id1)
    id2 = int(ctx.args.id2)

    r1 = get_results(ctx.args.machine, id1, system_config, rt_suites, suites)
    r2 = get_results(ctx.args.machine, id2, system_config, rt_suites, suites)

    for e in r1:
        c = lookup_entry(r2, e[0], e[1])
        if not c:
            continue
        diff = 0
        if c[3] != 0:
            diff = (e[3] - c[3]) / c[3] * 100
        val = f'{e[3]:>10.2f}/{c[3]:>10.2f}'
        print(
            f'  {e[0]:20} {e[1]:20} {e[2] + "/" + c[2]:20} '
            f'{val:10} {diff:>10.2f}%'
        )
