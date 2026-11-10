"""Jobs hack command - boot a board like an earlier job and keep it up.

Takes the deploy and boot actions of an existing LAVA job (so the same
kernel, dtb and rootfs) and replaces its tests with an inline one that
installs an SSH key, starts sshd, prints the board's address and then
waits, so you can log in and debug:

  srt-build jobs hack 67 --minutes 90
  ssh root@<address>          # printed once the board is up
  touch /tmp/hack-done        # on the board: end the session early

To catch something right after boot (as the real tests run ~30 s after
it), copy scripts with --file and start one with --run before the wait;
its output goes to the job log:

  srt-build jobs hack 67 --minutes 10 --file trace-run.sh \
      --run "./trace-run.sh sv svsematest -q -t -a -p 98 -D 1m -b 1000"

The session also ends after --minutes, or with `jobs cancel`.
"""

import base64
import copy
import os
import re
import sys
import time

import yaml

from ..lava_api import LavaApi, rpc_from_lavacli

DONE_FILE = "/tmp/hack-done"
IP_MARKER = "SRT_HACK_ADDR="


def add_parser(subparser):
    p = subparser.add_parser(
        "hack", help="boot a board like job ID and keep it up for SSH"
    )
    p.add_argument("id", type=int, help="LAVA job to take kernel/rootfs/board from")
    p.add_argument(
        "--minutes", type=int, default=60, help="how long to keep the board (60)"
    )
    p.add_argument(
        "--key",
        default="~/.ssh/id_ed25519.pub",
        help="public key to install for root (~/.ssh/id_ed25519.pub)",
    )
    p.add_argument(
        "--kernel", metavar="URL", help="boot this kernel image instead of the job's"
    )
    p.add_argument(
        "--kernel-args",
        metavar="ARGS",
        help="add ARGS to the kernel command line (e.g. a flavor's)",
    )
    p.add_argument(
        "--file",
        action="append",
        default=[],
        metavar="PATH",
        help="copy this local file to /root on the board (repeatable)",
    )
    p.add_argument(
        "--run",
        metavar="CMD",
        help="run CMD in /root right after boot, before the wait",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="print the job definition only"
    )
    p.add_argument(
        "--no-wait",
        action="store_true",
        help="don't wait for the board to come up and print its address",
    )
    p.set_defaults(func=cmd_jobs_hack)
    return p


def _copy_steps(files):
    """Shell lines that recreate {name: bytes} in /root (base64, one line
    each, so nothing in the file can break the test script)."""
    steps = []
    for name, data in files.items():
        b64 = base64.b64encode(data).decode()
        steps.append(f"echo {b64} | base64 -d > /root/{name}")
        steps.append(f"chmod +x /root/{name}")
    return steps


def hack_definition(
    definition, pubkey, minutes, kernel=None, files=None, run=None, kernel_args=None
):
    """The hacking-session job for an existing job definition (YAML text).

    files: {name: bytes} to put in /root; run: command to run in /root
    after sshd is up and before the wait."""
    job = yaml.safe_load(definition)
    actions = [a for a in job["actions"] if "test" not in a]
    if kernel:
        for a in actions:
            if "deploy" in a and "kernel" in a["deploy"]:
                a["deploy"]["kernel"]["url"] = kernel
    seconds = minutes * 60
    steps = [
        "mkdir -p /root/.ssh && chmod 700 /root/.ssh",
        f"echo '{pubkey}' >> /root/.ssh/authorized_keys",
        "chmod 600 /root/.ssh/authorized_keys",
        "systemctl start sshd || /usr/sbin/sshd",
        f"rm -f {DONE_FILE}",
        "uname -a",
        "for a in $(ip -4 -o addr show scope global | awk '{print $4}'); do"
        f" echo {IP_MARKER}${{a%/*}}; done",
    ]
    steps += _copy_steps(files or {})
    if run:
        steps += [f"(cd /root && {run}) || echo hack: run exited $?"]
    steps += [
        f"end=$(( $(date +%s) + {seconds} ))",
        # A line now and then, so the console never goes quiet for long.
        f"while [ ! -e {DONE_FILE} ] && [ $(date +%s) -lt $end ]; do"
        " sleep 60; echo hack: $(( (end - $(date +%s)) / 60 )) min left; done",
    ]
    test = {
        "test": {
            "timeout": {"minutes": minutes + 5},
            "definitions": [
                {
                    "from": "inline",
                    "name": "hack",
                    "path": "inline/hack.yaml",
                    "repository": {
                        "metadata": {
                            "format": "Lava-Test Test Definition 1.0",
                            "name": "hack",
                            "description": "keep the board up for SSH",
                        },
                        "run": {"steps": steps},
                    },
                }
            ],
        }
    }
    hack = copy.deepcopy(job)
    if kernel_args:
        context = dict(hack.get("context") or {})
        extra = context.get("extra_kernel_args", "")
        context["extra_kernel_args"] = f"{extra} {kernel_args}".strip()
        hack["context"] = context
    hack["actions"] = actions + [test]
    hack["job_name"] = f"hack ({job.get('job_name', 'job')})"
    hack["timeouts"] = dict(hack.get("timeouts") or {})
    hack["timeouts"]["job"] = {"minutes": minutes + 20}
    return yaml.safe_dump(hack, sort_keys=False)


def find_addresses(log):
    found = re.findall(re.escape(IP_MARKER) + r"([0-9.]+)", log or "")
    return list(dict.fromkeys(found))


def _wait_for_address(api, job_id, timeout=900):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        job = api.job(job_id)
        if job.get("state") != last:
            last = job.get("state")
            print(f"job {job_id}: {last}", flush=True)
        if job.get("state") == "Finished":
            return None
        if job.get("state") == "Running":
            addrs = find_addresses(api.log(job_id))
            if addrs:
                return addrs
        time.sleep(15)
    return None


def cmd_jobs_hack(args, system_config, machine_config):
    with open(os.path.expanduser(args.key)) as f:
        pubkey = f.read().strip()
    api = LavaApi.from_config(system_config)
    src = api.job(args.id)
    files = {}
    for path in args.file:
        with open(os.path.expanduser(path), "rb") as f:
            files[os.path.basename(path)] = f.read()
    definition = hack_definition(
        src["definition"],
        pubkey,
        args.minutes,
        args.kernel,
        files,
        args.run,
        args.kernel_args,
    )
    if args.dry_run:
        print(definition)
        return
    rpc = rpc_from_lavacli(identity=system_config.get("lava-identity", "default"))
    ids = rpc.scheduler.jobs.submit(definition)
    job_id = ids[0] if isinstance(ids, list) else ids
    print(
        f"job id: {job_id}  (board {src.get('actual_device') or '?'},"
        f" {args.minutes} min)"
    )
    if args.no_wait:
        return
    addrs = _wait_for_address(api, job_id)
    if not addrs:
        print(f"job {job_id} didn't come up; see its log", file=sys.stderr)
        sys.exit(1)
    for a in addrs:
        print(f"ssh root@{a}")
    print(f"end early: ssh root@{addrs[0]} touch {DONE_FILE}")
