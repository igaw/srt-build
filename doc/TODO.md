# TODO

Tooling work for srt-build, most useful first. Findings about the
kernel and its tuning go to `TUNING.md` ("Open questions").

## The job interface

Submitting and following a round is error prone and gets out of sync
easily:

- A round is several commands per board: `lava <board> --skip-build`
  for the default round, `lava <board> --skip-build --flavors rt
  --testsuites stress-ng-class` for the stress classes. Nothing names
  "round 12" as a whole; which jobs belong to it is rebuilt by hand
  from the printed ids or LAVA's job list.
- `--testsuites` takes one suite, and the default round is the suite
  called `smoke`: `--testsuites default stress-ng-class` looks right
  and fails.
- `lava` prints only one job id per command, while submitting a dozen
  jobs.
- The job database knows only what this checkout submitted: a stale
  checkout elsewhere (jobs 782-792 from nitrogen) or a job submitted by
  hand isn't in it, and `jobs report` without `--ids` misses it.
- Waiting for a round, or for one job, is a loop around LAVA's API in a
  shell (`jobs watch` covers part of it).
- Without `--ids`, `jobs report` and `jobs export` take each board's
  last `lava` command from the database: after the two commands of a
  round, only the stress-ng class jobs, not the default round. `jobs
  export` should rather send everything not sent yet.
- Nothing shows which srt-build a submission uses before it's too late:
  jobs 782-792 came from a nitrogen checkout that hadn't pulled, and
  round 12's second try (858-911) from one without commits that weren't
  pushed yet; `srt.build` in the job metadata only tells afterwards.
  `lava` should print the version it submits and warn when the
  checkout is behind its upstream or dirty.
- `jobs results` and `jobs compare` know the per-test jobs only: they
  pick the RT results by the suite names `0_<test>` (`rt_suites` in
  `config.yml`), and a combined job's suites are `<n>_<test>`, so its
  results are shown without the RT handling.
- The LAVA server's disk is part of a round's conditions: 20G ran full
  with four combined jobs at once (round 12, first try). Check the free
  space before a round and while it runs, and let `jobs report` call
  "No space left on device" an infrastructure failure, not a test one.

## Plan: rounds and the round archive

The fix for all of the above, agreed 2026-11-13: a round becomes the
unit that is submitted, followed, reported and exported; its results
go to an archive of plain files that srt-build manages, the master copy
(LAVA has no backup, VictoriaMetrics is filled from the archive); the
job database is extended to know rounds; the dashboards put the round
on the x axis. The design, the steps and what each must show:
[ROUNDS.md](ROUNDS.md). Step 1 backfills rounds 10-13 before
Artifactorial drops their uploads (90 days, 2027-02-10).

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
- Re-exporting jobs from before the workload label (`jobs export
  --force`) would add a second series next to the old one: delete the
  old series in VictoriaMetrics first.
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
