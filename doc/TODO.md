# TODO

Tooling work for srt-build, most useful first. Findings about the
kernel and its tuning go to `TUNING.md` ("Open questions").

## First: a reliable test setup

The base work before anything else: every high latency of the stress-ng
classes explained as the kernel's or the test's. Flagged tests, the two
kinds (rtla user space only, 10-20 ms: solved, the patched rtla of
rootfs-2026.11.22; the kernel side at 1 ms on the Pis: open) and the plan (locked memory, one stressor at a time, kernel or
PREEMPT_RT, report the kernel side apart): TUNING.md, "A reliable
setup first". Tooling it needs here: the kernel side (`t`, `i`) apart
from rtla's user space (`u`) in `round report` and the dashboards.

## Rounds: what is left

Rounds and the round archive ([ROUNDS.md](ROUNDS.md)) replaced the
job interface's old troubles: several `lava` commands per board, the
`--testsuites default stress-ng-class` trap, one job id printed, a job
database per checkout, shell loops to wait, `jobs report` without
`--ids` taking each board's last command, no version or disk check
before submitting. Every submission is now a round in the archive
(`round start`: release, `lava`: test), the archive is the only record.
Left:

- Round 13 (966-1019): `round import` once it has finished.
- VictoriaMetrics: delete the old series of rounds 10-13 and re-export
  them from the archive (`round export --all`). Exported before the
  upload fix, they lack the histograms of rtla-timerlat-idle,
  rtla-timerlat and cyclictest-idle.
- Grafana: check the version on monitor (Trend panel: 10+) before
  deploying the dashboards.
- Artifactorial keeps uploads until deleted (its expiry isn't
  scheduled): `round report` deletes them once archived; a scheduled
  `manage.py clean` (homelab) would be a safety net, the user's call.
- Round 14: the first round with `round start`/`wait`/`report`/`export`
  only.

## The job interface: still open

- `jobs results` and `jobs compare` know the per-test jobs only: they
  pick the RT results by the suite names `0_<test>` (`rt_suites` in
  `config.yml`), and a combined job's suites are `<n>_<test>`, so its
  results are shown without the RT handling. `round compare` covers
  combined jobs; the old commands could go.
- The LAVA server's disk is part of a round's conditions: 20G ran full
  with four combined jobs at once (round 12, first try). `round start`
  and `round wait` check the free space; `jobs report` should still
  call "No space left on device" an infrastructure failure, not a test
  one.

## Latency limits learned from history

`jobs report` flags a max latency only above a fixed 1 ms. Learn a
band per board, flavor, test, workload and kernel series from the
reference rounds in VictoriaMetrics (from round 12 on, the results
carry their workload) and flag what falls outside it; "no baseline"
while there are too few rounds.

## Dashboards by workload

The dashboards group by board, flavor and test. With more than one
workload per test (step 4 of the workload plan: fewer tests under
more workloads) they must group, and let one choose, by workload too.

## Rounds: more workloads, fewer hackbench runs

Almost every test runs under hackbench, which loads mostly the
scheduler and IPC. Measure fewer tests under more workloads instead:
cyclictest and rtla-timerlat under idle (done: the baseline),
hackbench, the stress mix and a memory/IO load; the IPC tests
(pmqtest, ptsematest, svsematest, sigwaittest) under one workload each.
Changes the default round, so it needs a decision first.

Related: the test label of the idle runs is `cyclictest-idle`, next to
the workload `idle`; a test label for the measuring tool alone
(`cyclictest`, workload `idle`) would line the workloads up in one
series. A combined job needs unique definition names, so this would be
a mapping in the export.

## Hack sessions keep their data

A hack session's board and its NFS root are gone when the session
ends: hack job 755's data was lost that way. The night of 2026-11-12
copied `/root/out` off every board every 5 minutes with scripts kept
outside the repository (a sync loop over the running hack jobs, a
watcher, a summary of the class-run stops). `jobs hack` should copy an
output directory off by itself, before the session ends, and those
scripts belong in `contrib/hack/`.

## rtla histogram range

`rtla timerlat hist` counts everything above its last bucket as
"over": bbb's Usr column had 4772 samples above 256 us in job 730,
with no shape. A wider range (`-E`) would keep it.

## Build on another machine (later: no fast machine yet)

Ideas from 2026-11-23, for when a fast build machine is in the lab; until
then everything builds on nitrogen. The release steps (srt queue, sign,
upload, push) stay local with the maintainer's key; building and testing
move. stable-rt-tools' `srt test` phases make the split possible:
TEST_COMMAND builds and submits, TEST_WAIT and TEST_CHECK stay where the
round archive is.

Getting the release to the build machine (its tags are local until srt
push):

- **An internal git tree.** A `lab` repository on Forgejo (pot.lan) as a
  remote of the work area; TEST_COMMAND pushes the series and the
  release tags (`--force`: srt quilt undo makes the same tag again), the
  build machine fetches and checks out `{tag}`. Keeps the signed tags
  and the exact tree. Open: how the build machine reads it without a
  credential on a test VM (homelab rule): anonymous read only inside the
  LAN (check what git.lab.monom.org exposes), or nitrogen pushes into a
  plain repository on the build machine (no Forgejo, no credential
  there).
- **No git transfer at all.** Everything is a patch queue: the build
  machine takes the public upstream tree (stable, `{upstream}`), gets
  the queue (`-patches` worktree, as tar or quilt series), applies it and
  builds. No internal repository, nothing to synchronize but the
  patches. Downside: the build isn't of our tags and tree; the result
  must be the same tree as `{tag}` (compare the tree hash, as srt quilt
  release does with -rebase).

srt-build then needs:

- A build-only round step (`round build`, or `lava --no-submit`): build
  and install every flavor of config.yml rounds on the build machine
  (toolchains, srt-build checkout, ssh to lava for the artifacts there).
- `round start --skip-build` on nitrogen submits with the kernels just
  installed, by the same names on both machines, and the round lands in
  nitrogen's archive (round wait, compare).

## Secrets out of the repository

The Artifactorial token is in `jobs/boards/*.yaml`, in a public
repository, and the jobs are public, so it is in their logs too. Move it
to a private file (LAVA `secrets:`, jobs not public) and rotate it.
Needs the next item first.

## Board files in layers

`load_job_ctx` takes the first board file it finds, so a file in
`~/.config/srt-build/` replaces the repository's whole. Load the
repository's, then a private one on top of it.

## Smaller

- The flavor is spelled into every job name (`'cyclictest
  rt-isolcpus'`); the smoke template exists once per flavor. job-base
  could add the flavor, and a flavor reuse another's templates (job
  names must stay the same: combined lists, reports, dashboards).
- `jobs/rt/stress-ng/stress-ng.items` comes from an older stress-ng;
  0.22.01 has about 17 more stressors. Each needs the OOM and FIFO
  checks of TUNING.md before it runs in a round.
- The per-test jobs run in file name order (`0004-`...), the combined
  job in `config.yml`'s order: two orders to keep in mind.
- Re-exporting jobs from before the workload label or with the round
  label (`round export`) adds a second series next to the old one:
  delete the old series in VictoriaMetrics first.
- LAVA's validate API doesn't check that test definition names are
  unique; only the dispatcher does, when the job starts (job 793). The
  unit tests check srt-build's jobs; a check before submitting would
  catch jobs written by hand too.

## Outside srt-build

- Linaro/test-definitions PR #652: a draft until rounds 12 and 13 come
  back clean with the final series, then ready for review.
- The scheduler WARNING under stress-ng cpu-sched on rpi3-64 (TUNING.md,
  open questions): check it against mainline, then report upstream.
- The rootfs (kiwi-lava): procps' `ps` and `pkill` fail on kernels
  without NUMA ("get_mempolicy: Function not implemented"); scripts on
  the boards go through `/proc` instead.
