"""Smoke test command - run quick smoke tests on LAVA."""

import os
import tempfile
from ..config import bcolors
from ..helpers import (
    ensure_lavacli_available,
    convert_to_seconds,
    load_job_ctx,
    generate_job,
    generate_split_files,
    save_job_ids,
)
from ..core import run_cmd
from .cmd_install import cmd_install


def add_parser(subparser):
    """Add smoke command parser."""
    spsg = subparser.add_parser("smoke")
    spsg.add_argument("machine", help="Target machine")
    spsg.add_argument("--duration", default="5m")
    spsg.set_defaults(func=cmd_smoke)
    return spsg


def cmd_smoke(ctx, system_config):
    """Run smoke tests on LAVA."""
    # Check if kernel exists first
    kernel_image = os.path.join(ctx.build_path, ctx.image)
    if not os.path.exists(kernel_image):
        print(
            f"{bcolors.FAIL}Error: Kernel image not found at "
            f"{kernel_image}{bcolors.ENDC}"
        )
        print(
            f"{bcolors.WARNING}Please build the kernel first with: "
            f"./srt-build-new build {ctx.args.machine}{bcolors.ENDC}"
        )
        return

    ensure_lavacli_available()
    duration = convert_to_seconds(ctx.args.duration)

    jobs = []

    ctx.args.dest = "lava"
    ctx.args.postfix = ""
    cmd_install(ctx)

    with tempfile.TemporaryDirectory() as td:
        job_ctx = load_job_ctx(ctx.job_path + "/boards/" + ctx.hostname + ".yaml")
        job_ctx["tags"] = [ctx.hostname]
        testname = "job-smoke-tests"
        filename = ctx.job_path + "/" + testname + ".jinja2"
        job = generate_job(ctx.job_path, filename, job_ctx)
        files = generate_split_files(td, job, ctx.hostname, duration)
        for j in files:
            (_, res) = run_cmd(["lavacli", "jobs", "submit", j])
            jobs.append(str(res).strip())

    save_job_ids(ctx, jobs, system_config)
