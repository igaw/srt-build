# srt-build

tooling to build RT test kernels with Lava.

## Checking a test round

    srt-build jobs watch --since 12       # follow all LAVA jobs after job 12
    srt-build jobs report                 # latest run of every board
    srt-build jobs report bbb --ids 13-27 --save ~/lava-runs/r3

`jobs report` puts all jobs of a round into one table: health, maximum
latency, uploads and problems. A job counts as a problem when LAVA
reports it Incomplete, but also when it is Complete and still broken:

- a test case or LAVA action failed (e.g. power-off),
- an upload of a result file failed,
- a test definition ran but reported no results (a test script that
  crashed after the measurement),
- the board's console shows a kernel warning, BUG, Oops, panic, RCU
  stall or hung task, or a test-script error (Python traceback, curl
  error, `command not found`).

Without `--since`/`--ids` the jobs come from srt-build's job database,
the last run of each board. The report reads LAVA's REST API, located
from the lavacli identity (`~/.config/lavacli.yaml`, identity `default`;
`lava-api`/`lava-identity` in `system_config` override it). Both
commands exit with 1 if any job has a problem.

`jobs watch` prints each job that finishes with a problem as soon as it
does, and the report when all jobs have finished and no new one came
for `--settle` seconds (default 600).

## Debugging on a board

    srt-build jobs hack 67 --minutes 90   # boot like job 67, keep it up
    ssh root@<address>                    # printed once the board is up

`jobs hack` takes the deploy and boot actions of an existing LAVA job
(same board, kernel, dtb and rootfs; `--kernel URL` swaps the kernel)
and replaces its tests with an inline one that installs your SSH key
(`--key`, default `~/.ssh/id_ed25519.pub`), starts sshd, prints the
board's address and waits. `touch /tmp/hack-done` on the board ends the
session early. It submits through the lavacli identity's XML-RPC, so
lavacli itself needn't be installed.

The tests run about 30 s after boot, and some effects only show then.
`--file` copies local scripts to `/root` and `--run CMD` starts one
right after boot, before the wait; its output lands in the job log:

    srt-build jobs hack 67 --minutes 10 --file trace-run.sh \
        --run "./trace-run.sh sv svsematest -q -t -a -p 98 -D 1m -b 1000"

## Checking kernel configs

    srt-build config c2d --check          # in the kernel tree

configures every flavor of the board in a scratch directory and shows
what it ends up as (preemption model, PREEMPT_RT, PREEMPT_DYNAMIC, SMP,
tick mode, HZ), plus every value a fragment requests that isn't in the
final config: renamed or removed symbols, and dependencies the
architecture doesn't meet.

## Development

Quickstart:

1. Create a virtualenv and install dev tools:
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt

2. Format and lint:
   black .
   ruff check .

3. Run tests:
   pytest -q

The CI pipeline runs linting, formatting checks and the smoke tests on each PR.
