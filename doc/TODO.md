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

Wanted: a round as a first-class thing: `srt-build round start
[--boards ...] [--suites smoke,stress-ng-class]` that submits
everything, records the round (number, srt-build and test-definitions
version, kernel, job ids) and prints it whole; `round status`, `round
wait` and `round report` that take the round, not job ids.

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
