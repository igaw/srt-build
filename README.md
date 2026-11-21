# srt-build

tooling to build RT test kernels with Lava.

The user documentation is in `docs/` (Sphinx, `make -C docs html`):
installation, configuration, testing a release, rounds, debugging on a
board, agents and the command line.

## Rounds

A round is the unit that is submitted, followed, reported and
exported; its results go to the round archive
(`~/.local/share/srt-build/rounds`, `round-archive` in `system_config`),
the master copy and the only record of what was submitted
(doc/ROUNDS.md). Release rounds (10, 11, ...) are the reference runs:
`round start` builds and installs every board's kernels (`--skip-build`:
the installed ones), then submits, per board, one `lava --skip-build`
per entry of
`rounds: submissions` in `config.yml`. Everything else is a test round
(t1, t2, ...): each `lava` or `smoke` command makes one, and `round
prune` drops them after `test-retention-days`.

    cd ~/linux                            # the kernel tree, as for lava
    srt-build round start --dry-run       # what it would submit
    srt-build round start                 # build, install, release round
    srt-build round start --skip-build    # with the kernels installed already
    srt-build round start --test --notes "nohz=off"   # test round t1, t2, ...
    srt-build round status                # every job's state, LAVA's free disk
    srt-build round wait                  # until all have finished
    srt-build round rerun 13 961          # a lab failure: run the job again
    srt-build round repeat 15             # its jobs again, a new round (no tree)
    srt-build round report                # fetch into the archive, the table
    srt-build round export                # to VictoriaMetrics, label round
    srt-build round compare 12 13         # max latency side by side
    srt-build round list                  # the rounds in the archive

Without a round id the commands take the round started last; `12` is a
release round, `t3` a test round. `round start` warns and asks when
the srt-build checkout has local changes, isn't in sync with its
upstream, or the LAVA server's disk is low. Every job carries
`srt.round` in its metadata.

`round report` fetches every finished job the archive doesn't have yet
(job, results, log, uploads; the Artifactorial token replaced), writes
`report.txt` and prints the `jobs report` table from the archive; run
it again for the jobs that weren't finished. Then it deletes the
archived uploads from Artifactorial (`--keep-uploads`: not). Rounds
that ran before `round start`:

    srt-build round import 12 --ids 912-965 --keep-uploads

Removing data, always after listing it and asking:

    srt-build round drop t2 --metrics     # archive, uploads, series
    srt-build round prune --dry-run       # test rounds past test-retention-days
    srt-build jobs purge --ids 755-777 --metrics   # hack sessions, outside rounds

## Running jobs by hand

    srt-build lava bbb                    # build, install, submit all flavors
    srt-build lava bbb --skip-build       # the installed kernels
    srt-build lava bbb --split            # one job (boot) per test
    srt-build lava bbb --testsuites stress-ng-class   # the stress classes

Each command is a test round: it prints its id (t4) and every job id,
and `round report t4` fetches it into the archive like any round.

A flavor with a `combined` list in `config.yml` (rt, rt-isolcpus) runs
those tests in one job ("rt-tests", "rt-tests rt-isolcpus"), one
boot, in that order; its other tests
(pi-stress) and all other flavors get a job per test. Each test of a
combined job stays a LAVA test suite of its own, so `jobs report`
lists it in a row under the job and `jobs export` sends its results
as that test's, as if it had its own job. `--split`, `--tests` and
other test suites give one job per test, for chasing a strange
result.

## Checking a test round

    srt-build jobs watch --since 12       # follow all LAVA jobs after job 12
    srt-build jobs report                 # the round started last
    srt-build jobs report bbb --ids 13-27 # these jobs, a quick look

For a round, `round wait` and `round report` do this and keep the
result in the archive; `jobs report` reads LAVA only (`--save DIR`
keeps its answers in DIR).

`jobs report` puts all jobs of a round into one table: health, maximum
latency, uploads and problems. A job counts as a problem when LAVA
reports it Incomplete, but also when it is Complete and still broken:

- a test case or LAVA action failed (e.g. power-off),
- an upload of a result file failed,
- a test definition ran but reported no results (a test script that
  crashed after the measurement),
- the board's console shows a kernel warning, BUG, Oops, panic, RCU
  stall or hung task, or a test-script error (Python traceback, curl
  error, `command not found`),
- a max latency above 1 ms.

A boot that LAVA had to retry (bbb, see doc/TUNING.md) is shown as
"retried", not as a problem.

Without `--since`/`--ids` the jobs are those of the round started
last in the archive. The report reads LAVA's REST API, located
from the lavacli identity (`~/.config/lavacli.yaml`, identity `default`;
`lava-api`/`lava-identity` in `system_config` override it). Both
commands exit with 1 if any job has a problem.

`jobs watch` prints each job that finishes with a problem as soon as it
does, and the report when all jobs have finished and no new one came
for `--settle` seconds (default 600).

## Dashboards

    srt-build jobs export                         # the newest round not sent yet
    srt-build jobs export --ids 912-965 --dry-run # print these jobs' samples
    srt-build jobs export --since 242             # send every job after 242
    srt-build round export --all                  # every round not sent yet
    srt-build jobs watch --since 242 --export     # send the jobs when done
    srt-build jobs dashboard DIR --lava-url https://lava.example

`jobs export` turns each finished job into VictoriaMetrics samples at
the job's end time: whether it had problems, min/avg/max latency per
thread, and the histograms of the rt-tests/rtla JSON uploaded to
artifactorial (see `srt_build/metrics.py`). It sends them to
`/api/v1/import` behind vmauth, as configured in
`~/.config/srt-build/metrics.yml` (`url`, `username`, `password`).

Without arguments `jobs export` is `round export` of the newest round
not exported yet: the samples built from the archive, with the labels
`round` and `round_kind`, and the round's round.yaml notes that it went
out. With `--ids`, `--since` or boards it sends exactly those jobs and
notes nothing: a job of an archived round gets its round's labels and
archived data, others are read from LAVA and artifactorial (where the
uploads stay until deleted: `round report`, `jobs purge`).

`jobs dashboard` writes the Grafana dashboards for these samples into
DIR, generated by `srt_build/grafana.py`: `rt-tests.json`, the overview,
a trend per board and test (max latency of each
job, a line per flavor), and `rt-test-detail.json`, one board, flavor
and test in depth (trends per thread, percentiles, the histograms over
time, one job's histogram and threads, jobs and kernels), and
`rt-rounds-compared.json`, two rounds (release or test, chosen at its
top) side by side, and `rt-problems.json`, the jobs with problems and a
few numbers over all jobs. A click on a trend in the overview opens its
details; they link to each other at the top. The green band in the trends is
the normal range of the release rounds (median +- 3 x 1.4826 x MAD, at
least +- 40 % and 20 us), red points the rounds above it: see
docs/dashboards.rst.

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

`contrib/hack/` has the scripts that found the lab's latency problems,
for such sessions; each says how to run it:

- `osnoise-trace.sh`: rtla-osnoise for hours in short runs, stops at
  the first sample above a threshold and keeps the scheduler trace
  (found the fair server running hackbench ahead of osnoise).
- `fair-server-ab.sh`: rtla-osnoise with 6.12's fair server on and
  off, alternating.
- `cyclictest-trace.sh`: cyclictest on the isolated CPUs with ftrace,
  stops at the first latency above a threshold (found the missing
  `isolcpus=domain`).

Copy the traces off the board (`scp root@<address>:/root/trace-*`)
before the session ends: the board's root file system is gone with it.

## Board tuning

[doc/TUNING.md](doc/TUNING.md) explains the boards' kernel configuration,
command line and runtime settings, the quirks found on the way and what
didn't help, with the LAVA jobs that showed it. What srt-build itself
still lacks is in [doc/TODO.md](doc/TODO.md).

## Checking kernel configs

    srt-build config c2d --check          # in the kernel tree

configures every flavor of the board in a scratch directory and shows
what it ends up as (preemption model, PREEMPT_RT, PREEMPT_DYNAMIC, SMP,
tick mode, HZ), plus every value a fragment requests that isn't in the
final config: renamed or removed symbols, and dependencies the
architecture doesn't meet.

## Agents (MCP)

`round list`, `round status`, `round compare` and `round report` take
`--json` for scripts. `srt-build mcp` serves the lab to an agent as an
[MCP](https://modelcontextprotocol.io) server on stdin and stdout; the
kernel trees are named relative to `--trees`:

    claude mcp add srt-build -- ~/srt-build/srt-build mcp --trees ~/rt

Its tools run srt-build itself, without a terminal:

- `boards`, `tests`, `rounds`, `round_status`, `round_compare`: read
  the configuration, the archive and LAVA;
- `round_report`, `round_export`: fetch and report a round, send it to
  VictoriaMetrics, as by hand;
- `lava` (build, install, submit a test round) and `round_start` (a
  round with the installed kernels, a dry run unless asked otherwise)
  run as tasks, which outlive the client, one per tree;
  `task_status` and `tasks` follow them;
- `round_rerun`, `round_drop`.

Whoever starts the server decides what the agent may do to the lab:
`lava`, a real `round_start` and `round_rerun` take the boards and
need `--allow-submit`; a real `round_drop` needs `--allow-delete`.
Without them the agent gets told to ask. The tasks' logs are in
`~/.local/state/srt-build/mcp`.

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
