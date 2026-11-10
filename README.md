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
