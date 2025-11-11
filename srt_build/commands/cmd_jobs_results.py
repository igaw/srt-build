"""Jobs results command - display LAVA job results."""

import re
from ..config import bcolors
from ..helpers import ensure_lavacli_available, get_job_list, get_jobs
from ..results import get_job_context, job_result_print
from ..core import run_cmd


def add_parser(subparser):
    """Add jobs results command parser."""
    rpsg = subparser.add_parser("results")
    rpsg.add_argument("machine", help="Target machine")
    rpsg.add_argument("id", nargs="?", default=None)
    rpsg.set_defaults(func=cmd_jobs_results)
    rpsg.add_argument("--raw", default=False, action="store_true")
    rpsg.add_argument("--batch", default=False, action="store_true")
    rpsg.add_argument("--kernel", default=False, action="store_true")
    rpsg.add_argument(
        "--download",
        default=False,
        action="store_true",
        help="download JSON result file",
    )
    rpsg.add_argument("--host")
    rpsg.add_argument("--description")
    return rpsg


def cmd_jobs_results(ctx, system_config, rt_suites, suites):
    """Display results for LAVA jobs."""
    if not ctx.args.id:
        jobs = get_job_list(ctx, system_config)
        if not jobs:
            print(
                f"No jobs found for machine {ctx.args.machine}. "
                f'Run a job first with "lava" or "smoke" command.'
            )
            return
        id = int(jobs[-1])
        batch = True
    else:
        id = int(ctx.args.id)
        batch = ctx.args.batch

    ensure_lavacli_available()

    metadata, job_ctx = get_job_context(id, ctx)
    if not metadata or not job_ctx:
        print(
            f"{bcolors.WARNING}Cannot display results for job {id}. "
            f"Job may not be assigned to a device yet.{bcolors.ENDC}"
        )
        return

    if ctx.args.raw:
        (_, res) = run_cmd(["lavacli", "jobs", "logs", str(id)])
        version = re.compile(r".*Linux version ([-0-9a-zA-Z\.]+)")
        m = version.search(res, re.MULTILINE)
        if m:
            metadata["version"] = m.group(1)
        else:
            metadata["version"] = ""

        (_, res) = run_cmd(["lavacli", "results", "--yaml", str(id)])

        if ctx.args.host and metadata["host"] != ctx.args.host:
            return
        if ctx.args.description and metadata["description"] != ctx.args.description:
            return
        print(
            f'{metadata["host"]}\t{metadata["description"]}\t' f'{metadata["version"]}'
        )
        job_result_print(
            id,
            job_ctx,
            metadata,
            res,
            system_config,
            rt_suites,
            suites,
            ctx.args.download,
        )
        return

    for j in get_jobs(ctx.args.machine, id, system_config, batch):
        (_, res) = run_cmd(["lavacli", "results", "--yaml", str(j)])
        job_result_print(
            j,
            job_ctx,
            metadata,
            res,
            system_config,
            rt_suites,
            suites,
            ctx.args.download,
        )
