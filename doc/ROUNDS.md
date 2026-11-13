# Rounds and the round archive

Every submission to the lab belongs to a round, and every round's
results are kept in an archive srt-build manages. This is the design
as built; "Status" at the end says what is left.

## Why

- A round used to be two `lava` commands per board, and which jobs
  belonged to it was rebuilt by hand from printed job ids (doc/TODO.md,
  "The job interface").
- LAVA has no backup (homelab `docs/hosts/lava.md`: "everything comes
  from the repo"): a rebuilt LAVA loses every job, log and result, and
  starts its job ids at 1 again. Its database layout isn't ours to
  depend on.
- The uploads (the rt-tests/rtla JSON with the histograms) live on
  Artifactorial. Its 90-day expiry is only applied by `manage.py
  clean`, which nothing schedules, so they stay until deleted (31 MB,
  1291 files on 2026-11-13). A scheduled `manage.py clean` (homelab)
  would be a safety net; the user's call.
- VictoriaMetrics is a view for analysis; it should be possible to fill
  it again from scratch.

So: the **round archive is the master copy** of the results and the
only record of what srt-build submitted. LAVA is where a round runs;
VictoriaMetrics is filled from the archive; Artifactorial only holds an
upload until the archive has it. The archive holds only what the
analysis needs, so it stays small and old rounds can be dropped.

## Not in scope

- Hack sessions (`jobs hack`) are not rounds and never go into the
  archive; `metrics.exportable` keeps them out of the exports too (job
  names "hack (...)", resubmits with arguments in parentheses). `jobs
  purge` deletes what they leave behind ("Deleting data").
- Deleting jobs in LAVA itself: that is for LAVA's admin on the server.
- Rounds 1-9: not archived, their data is deleted. The archive starts
  with round 10, the first clean reference.

## No database

The archive is the only state: the round.yaml files and the job
directories. What a database would index is found by reading them:

- the next round id (the highest of its kind, plus one);
- which round a job id belongs to, for the uniqueness guard ("Numbers
  and identity") and for `jobs export`'s labels;
- the round started last, the default of the round commands, `jobs
  report` and `jobs export`;
- what was exported (round.yaml `exported`), what is fetched (the
  `complete` markers), what was deleted from Artifactorial
  (`uploads.yaml`).

That is a scan of every round.yaml, fast for hundreds of rounds (test
rounds expire). If it ever gets slow, a cache built from the archive
can come then; it isn't built. Before rounds, a SQLite job database
(`~/.cache/srt-build/jobs.db`) kept `lava` commands per checkout; it is
gone, with its export record.

## The archive: plain files

Plain files, no schema to migrate; grep, diff, rsync and `rm -r` work
without srt-build. Location: `system_config["round-archive"]`, default
`~/.local/share/srt-build/rounds` (overridable in config.yml like
`metrics-config`).

```
<archive>/
  13/                       a release round
    round.yaml
    report.txt              format_report() of the round, for reading
    jobs/
      966/
        job.json            LAVA's REST job object (definition with metadata)
        tests.json          api.tests()
        suites.json         api.suites()
        log.yaml.gz         api.log(), gzip
        uploads/
          <suite>/<name>.json   each JSON upload, under its LAVA suite
                                (5_rtla-timerlat)
        uploads.yaml        each upload's URL, size, when it was deleted
                            from Artifactorial
        complete            empty; written last
  test/
    t1/                     a test round, laid out the same
```

- Directory names are the round id and the LAVA job id as plain
  decimal. Job ids are unique within a round's LAVA instance, which is
  all a round directory holds.
- Uploads are kept per suite: a combined job's tests upload files of the
  same name (rtla-timerlat-idle, rtla-timerlat and rtla-timerlat-stress
  all write rtla-timerlat.json, minutes apart, so Artifactorial doesn't
  rename them). `ArchiveApi.uploads()` gives them back under the names
  `metrics.artifact_urls()` uses: the bare file name if the job has it
  once, `<suite id>-<name>` if more than one suite uploaded it.
- gzip for the log (stdlib, 8:1 on job 912: 645 kB to 79 kB). The JSON
  files stay plain: small, and greppable. Rounds 10-12 take 4.6, 2.7
  and 6.0 MB.
- A job directory without `complete` is unfinished: the next `round
  report` fetches it again (also when an upload couldn't be fetched).

### round.yaml

```yaml
format: 1
round: 13                    # or t3 for a test round
kind: release                # release | test
lava: lava.lan               # system_config["lava-instance"]; job ids are per instance
started: '2026-11-13T12:20:00Z'
srt_build: 9e82b80d6821      # helpers.srt_build_version()
test_definitions:
  url: git://lava.lan/test-definitions.git
  branch: rt-tests-fixes
  commit: f6a8ad13...        # from the jobs' LAVA results, filled by round report
kernel: v6.12.117-rt23       # git describe of the kernel tree
notes: stress-ng classes only    # optional, free text (--notes)
imported: '2026-11-13T17:52:31Z' # round import only: when it was backfilled
boards: [bbb, c2d, rpi3-32, rpi3-64]
submissions:                 # the lava commands: config.yml rounds, or the
  - {}                       # options of a lava command (a test round)
  - {flavors: [rt], testsuites: stress-ng-class}
jobs:                        # every job submitted, with what it is
  966: {board: bbb, flavor: rt, test: rt-tests, submission: 0}
  ...
reruns:                      # old job: the job that replaces it
  961: 1020
reported: '2026-11-13T18:02:00Z'   # round report fetched everything
exported: '2026-11-13T18:05:00Z'   # round export sent it
```

Board, flavor and test per job come from the job's `srt.*` metadata
(`metrics.job_metadata`), so they also exist for imported rounds;
`submission` (the index into `submissions`) only for rounds `round
start` submitted. Keys with no value are left out.

### Writing

- Only srt-build's round code writes the archive: the round commands,
  and `lava`/`smoke` for their test rounds.
- Every file is written to `<name>.tmp` in the same directory and
  renamed: an interrupted run never leaves half a file.
- `round.yaml` is rewritten whole (tmp + rename): before the first job
  is submitted, after each submission, by `round rerun`, `import`,
  `report` and `export`.
- Secrets: before anything is written, every occurrence of the job's
  Artifactorial token is replaced by `<ARTIFACTORIAL_TOKEN>` in all of
  the job's files (job, tests, suites, log, uploads). The token is the
  `ARTIFACTORIAL_TOKEN` parameter in the job's own definition; its
  literal value is replaced everywhere, it shows up in the log's command
  lines too. LAVA's own token of the job (`token` in the REST job
  object, a secret of its own) becomes `<LAVA_JOB_TOKEN>`. Tests check
  that no file of a saved job contains either.

## Rounds

### Release rounds and test rounds

- Release rounds are the reference rounds: numbered 10, 11, ... without
  gaps, at `<archive>/<n>`, submitted by `round start`. Rounds 10-13
  are release rounds (11 only ran the stress-ng classes; its round.yaml
  says so in `notes`).
- Test rounds are everything else: each `lava` (and `smoke`) command is
  one, and `round start --test` makes one from config.yml's
  submissions. Numbered t1, t2, ... in a sequence of their own, at
  `<archive>/test/t<n>`, `srt.round: "t1"` in the jobs.
- Every round command takes either id: `round report t2`, `round compare
  13 t2`, `round export t2`.
- Test rounds expire: config.yml `rounds: test-retention-days` (default
  30); `round prune` drops those started longer ago ("Deleting data").
  Release rounds only go by an explicit `round drop`.
- Samples get `round_kind` ("release"/"test") next to `round`, and the
  dashboards show release rounds unless test rounds are chosen.

### A lava command is a test round

`srt-build lava <board> ...` writes a test round's round.yaml (its
options as the one entry of `submissions`, the kernel's git describe)
before it submits anything, tags every job with `srt.round`, adds the
jobs as they are submitted, and prints the round id and every job id
at the end. `srt-build smoke` does the same. A `lava` command inside
`round start` belongs to that round instead. `--list-tests` and
`--show-jobs` submit nothing and make no round.

### Numbers and identity

- The next round id is the highest of its kind in the archive plus one,
  or `round start --round N` (which must not exist yet). Not from LAVA:
  a reset LAVA starts its job ids at 1 again.
- A job is known by round and job id. `round.yaml` names the LAVA
  instance (`system_config["lava-instance"]`, default the host name of
  LAVA's API), so job 912 of two LAVA instances can be told apart.
- **Job ids never collide across rounds of one instance.** Before a job
  id goes into a round, every round.yaml of the same instance is
  checked (both kinds, rerun targets included, and the round's own
  jobs): `round import` refuses before writing anything, so a job is in
  one round only; `round start`, `round rerun` and `lava` check the ids
  LAVA returns. The error says that LAVA was probably reset and
  `lava-instance` needs a new name in config.yml. `round report`
  refuses to fetch a round of another instance.
- Every job of a round carries `srt.round: "13"` in its metadata
  (`jobs/job-base.jinja2`, next to `srt.build`, only when the context
  has a round: the environment is StrictUndefined). The archive stays
  the master; the tag lets LAVA's own UI see which round a job belongs
  to.

### What a round is: config.yml

```yaml
rounds:
  boards: [bbb, c2d, rpi3-32, rpi3-64]
  submissions:          # one lava submission per entry and board
    - {}                                          # = lava <board> --skip-build
    - {flavors: [rt], testsuites: stress-ng-class}
  test-retention-days: 30
```

This replaces the two commands per board, and the `--testsuites default
stress-ng-class` trap (the default round is the suite `smoke`). An
entry's keys are lava's options: flavors, testsuites, tests, split,
duration.

### Commands

`srt-build round ...`, a command group next to `jobs` (main.py,
commands/cmd_round*.py; what `lava` shares with them in rounds.py).
All but `start` run without the kernel tree.

- `round start [--boards ...] [--round N] [--test] [--notes] [--dry-run]
  [--yes]`
  - Before submitting: prints round, srt-build version, kernel, boards
    and the lava commands; warns and asks when the srt-build checkout
    has local changes, is behind or ahead of its upstream (`git status
    --porcelain`, `git rev-list --count HEAD..@{u}` and `@{u}..HEAD`
    after a fetch), or when the LAVA server's free disk is below
    `lava-disk-min-gb` (10; `ssh <lava-ssh> df /var/lib/lava`, default
    `root@<instance>`; "unknown" if not reachable).
  - Writes `round.yaml` (without jobs) before the first submission.
  - Runs the submissions per board through `cmd_lava` itself
    (`--skip-build`), with the round in the job context; `cmd_lava`
    returns the job ids, a submit hook records each job's board, flavor
    and test from its metadata.
  - Adds the jobs to `round.yaml` after each submission, prints the
    round whole at the end.
  - `--dry-run` renders every job and prints what it would submit;
    nothing is submitted or written (no git fetch either).
- `round status [N]` (default: the round started last): per job state
  and health from LAVA (from the archive for whole jobs), the rerun
  mapping, free disk on the LAVA server.
- `round wait [N] [--interval S]`: block until every job (after reruns)
  is Finished; one line per job that finishes not Complete, as it
  happens; a warning when the disk runs low. Exit 1 if a job ended not
  Complete.
- `round rerun N JOB`: resubmit JOB's definition unchanged (it carries
  `srt.round`) through XML-RPC (`lava_api.rpc_from_lavacli`), record
  `reruns: {JOB: NEW}`; `reported` is cleared. For lab failures; the
  replaced job stays in the archive but counts nowhere.
- `round report [N] [--keep-uploads]`: fetch every finished job that has
  no `complete` into the archive (job, tests, suites, log, uploads;
  scrubbed), fill `test_definitions`, write `report.txt`, print the
  report; then delete the archived uploads from Artifactorial ("Deleting
  data"). Reads from the archive: `report.summarize_job` takes the
  archived files exactly as it takes LAVA's answers. A job not finished
  is shown so and fetched next time; LAVA isn't asked at all when the
  archive has everything. Jobs replaced by a rerun and jobs not whole in
  the archive get a line under the table. Exit 1 on problems.
- `round compare A B`: board, flavor, test and workload of two rounds
  side by side (max latency, change in %), then the jobs with problems,
  from the archive.
- `round export [N | --all] [--dry-run] [--force]`: build the samples
  from the archive (`metrics.job_samples(job, tests, summary, uploads)`
  with everything read from files), add the labels `round` and
  `round_kind`, send them; set `exported` in round.yaml. Replaced jobs
  are left out. Without N: the newest round not exported yet; a round
  that was is sent again only with `--force`; `--all --force` refills
  VictoriaMetrics from the whole archive.
- `round list [--test]`: the release rounds (with `--test` also the
  test rounds), one line each (id, date, kernel, srt-build, jobs,
  fetched, exported, the report's summary).
- `round drop N` / `round prune`: see "Deleting data".
- `round import N --ids LIST [--test] [--notes] [--keep-uploads]`: a
  round from jobs that already ran (rounds 10-13); round.yaml from
  their metadata (LAVA health checks left out), then as `round report`.
  Importing more ids into an existing round adds them (careful: `round
  import 12 --ids 960-970` adds 966-970 to round 12 if no other round
  has them yet).

### The jobs commands

- `jobs report` without `--ids`/`--since`: the jobs of the round
  started last, reruns in place; with them, any LAVA jobs, for a quick
  look (`--save DIR` keeps LAVA's answers in DIR).
- `jobs export` without arguments: `round export` of the newest round
  not exported yet. With `--ids`, `--since` or boards: exactly those
  jobs, nothing noted; a job of an archived round gets its round's
  labels and archived data, any other job is read from LAVA and
  Artifactorial. Nothing is tracked per job any more.
- `jobs results`, `jobs cancel` and `jobs list` find "the board's last
  run" in the archive: the board's jobs in each round.
- `jobs watch --export` sends the jobs it watched, as `jobs export
  --since` would.

## Deleting data

Never by hand on one side only: the commands remove a round from
everywhere, list what will go and ask (`--yes` for scripts, `--dry-run`
to only list).

- Artifactorial (the lab's fork, ~/Artifactorial): `DELETE
  <base>/artifacts/<path>?token=<token>` deletes an artifact (views.py
  `_delete`; a post_delete signal removes the file); 403 if the token's
  user can't write it, 404 if gone (counted as deleted). The token is
  the jobs' upload token (`artifactorial_token` in the board files;
  `artifactorial-token` in system_config overrides it), which owns
  /rt-tests. The path is the part of the upload URL after `/artifacts/`,
  taken from the URL. The token is never printed; errors name the path.
- `round report` deletes each upload of a job that is whole in the
  archive, after checking the copy (there, the size it had when fetched,
  parses as JSON). `uploads.yaml` records when, so the next report
  doesn't ask again; a copy that doesn't verify is kept on Artifactorial.
  `--keep-uploads` deletes nothing (rounds 10-12 were imported with it:
  their uploads are still on Artifactorial).
- `round drop N [--metrics]` removes the round's archive directory, its
  uploads still on Artifactorial (those not deleted yet; of jobs never
  archived, found through LAVA), and with `--metrics` its series in
  VictoriaMetrics (`/api/v1/admin/tsdb/delete_series` with
  `{round="N", round_kind="..."}`).
- `round prune [--metrics]`: the same for every test round past its
  retention.
- `jobs purge --ids LIST [--metrics]`: for jobs outside rounds (hack
  sessions, e.g. the stress-ng night 755-777): their uploads, found
  through LAVA's test results, and with `--metrics` their series
  (`{job="<id>"}`). Refuses job ids of an archived round (`round drop`
  is for those).
- All deletion code is tested against fakes only; the tests can't reach
  a server at all (tests/conftest.py fails every urlopen a test doesn't
  fake).

## VictoriaMetrics and the dashboards

- Samples of round jobs get the labels `round` ("13", "t3") and
  `round_kind` ("release", "test"). `round_kind`, not `kind`:
  `srt_job_problems` already has a label `kind` (health, failed, ...),
  and the two would overwrite each other. The `job` label stays (the
  dashboards link to LAVA with it).
- A new label is a new series: before rounds 10-13 are exported from
  the archive, delete their old series in VictoriaMetrics (the user's
  call). Those old series also lack histograms: a combined job exported
  only the last of its uploads of one name, so the histograms of
  rtla-timerlat-idle, rtla-timerlat and cyclictest-idle were dropped
  (round 12: 660 of 7666 samples; fixed in `metrics.artifact_urls`). A
  re-export from the archive (`round export --all`) brings them back.
- Dashboards (`grafana.py`, rendered by `jobs dashboard`): in the
  overview, per board and test, a Trend panel with the round on the x
  axis: an instant query over the range, format table,
  `max by (round, flavor) (max_over_time(srt_latency_us{<sel>, stat="max"}[$__range]))`,
  `groupingToMatrix` (a column per flavor), "Convert field type" making
  the round a number, a line per flavor; a bar chart for two rounds
  side by side (`round_a`, `round_b`). A `round_kind` variable, release
  by default, keeps test rounds out of the normal view; the other panels
  also match samples without the label (jobs outside rounds). Test
  round ids (t3) aren't numbers, so the Trend panel is for release
  rounds. The Trend panel needs Grafana 10+: check the version on
  monitor before deploying. The time-based detail dashboard stays.

## Status

Built and tested (on fakes for everything that submits or deletes):
the archive, release and test rounds, `lava`/`smoke` as test rounds,
all round commands, `jobs export`/`report` on the archive, `jobs
purge`, the dashboards.

Checked on real data (read-only, into a scratch archive): rounds 10
(jobs 641-715, the 75 jobs with `srt.build` 81767acfe5fb), 11 (730-753)
and 12 (912-965) import whole, with all 172 uploads; their reports
equal the ones `jobs report --save` wrote at the time (round 11's
differs only by the "invoked oom-killer" findings, a pattern added
later); `round export 12 --dry-run` gives 7666 samples, the 7006 of
`jobs export` before the upload fix plus the 660 recovered; no archived
file contains the Artifactorial token or a LAVA job token.

Left:

- Round 13 (966-1019): `round import 13 --ids 966-1019 --keep-uploads`
  once its jobs have finished (or before: unfinished jobs are recorded,
  a later `round report 13` fetches them).
- VictoriaMetrics: delete the old series of rounds 10-13 (no round
  label, missing histograms), then `round export --all`.
- Grafana: check the version on monitor (Trend panel: 10+), then
  deploy the dashboards.
- Artifactorial: rounds 10-12's uploads were kept; `round report 10`
  (and 11, 12) without `--keep-uploads` deletes them once verified.
- Round 14 as the first round started with `round start`, followed with
  `round wait`, reported and exported with the round commands only.
