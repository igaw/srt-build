# TODO

Tooling work for srt-build, most useful first. Findings about the
kernel and its tuning go to `TUNING.md` ("Open questions").

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

## rtla with locked memory on armv7

Until a kernel with the rtla mlock fix is in the lab, the stress runs'
Usr column on bbb and rpi3-32 includes page faults of rtla's own
threads (TUNING.md, "rtla does not lock its memory"). The patched rtla
exists for arm64 and x86; building it for armv7 failed (no
arch/arm/Makefile in the tools build, ld crashing under emulation).
Either build it natively on an armv7 board or carry the patch in the
rootfs (kiwi-lava). Meanwhile read the Thr column on those boards.

## rtla histogram range

`rtla timerlat hist` counts everything above its last bucket as
"over": bbb's Usr column had 4772 samples above 256 us in job 730,
with no shape. A wider range (`-E`) would keep it.

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
