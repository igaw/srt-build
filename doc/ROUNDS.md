# Rounds and the round archive

Design for making a test round first-class in srt-build and keeping its
results in an archive srt-build manages. Agreed 2026-11-13; not
implemented yet. Steps and what each must show are at the end.

## Why

- A round today is two `lava` commands per board, and which jobs belong
  to it is rebuilt by hand from printed job ids (doc/TODO.md, "The job
  interface", lists what goes wrong).
- LAVA has no backup (homelab `docs/hosts/lava.md`: "everything comes
  from the repo"): a rebuilt LAVA loses every job, log and result, and
  starts its job ids at 1 again. Its database layout isn't ours to
  depend on.
- Artifactorial keeps the uploads (the rt-tests/rtla JSON with the
  histograms) 90 days only (`cmd_jobs_export.fetch_artifacts`).
- VictoriaMetrics is a view for analysis; it should be possible to fill
  it again from scratch.

So: the **round archive is the master copy** of the results. LAVA is
where a round runs; VictoriaMetrics and any index are derived from the
archive. The archive is kept apart from other backups and holds only
what the analysis needs, so it stays small and old rounds can be dropped.

## Not in scope

- Hack sessions (`jobs hack`) and jobs submitted by hand: not part of a
  round. `jobs export` keeps working for them as today.
- A second database next to the job database: rounds extend the one
  that exists (below, "The job database").

## The archive: plain files

A directory tree, no database. The data is written once and then only
read; most of it is files already (logs, LAVA's JSON, the uploads); no
schema of ours to migrate; grep, diff, rsync and `rm -r` work without
srt-build. The index and the bookkeeping (which jobs a round has, what
is fetched, what is exported) are the job database, extended (next
section); it can be rebuilt from the archive's `round.yaml` files, so
the files stay the master.

Location: `system_config["round-archive"]`, default
`~/.local/share/srt-build/rounds` (config.py `system_config`, overridable
in config.yml like `metrics-config`).

```
<archive>/
  13/
    round.yaml
    report.txt              format_report() of the round, for reading
    jobs/
      966/
        job.json            LAVA's REST job object (definition with metadata)
        tests.json          api.tests()
        suites.json         api.suites()
        log.yaml.gz         api.log(), gzip
        uploads/
          <name>.json       each JSON upload (metrics.artifact_urls)
        complete            empty; written last
```

- Directory names are the round number and the LAVA job id as plain
  decimal.
- gzip for the log (stdlib, 8:1 on job 912: 645 kB to 79 kB; round 12's
  logs are most of its 15 MB). The JSON files stay plain: small, and
  greppable.
- A job directory without `complete` is unfinished: the next `round
  report` fetches it again.

### round.yaml

```yaml
format: 1
round: 13
lava: lava.lan               # system_config["lava-instance"]; job ids are per instance
started: 2026-11-13T12:20:00Z
srt_build: 9e82b80d6821      # helpers.srt_build_version()
test_definitions:
  url: https://github.com/igaw/test-definitions.git
  branch: rt-tests-fixes
  commit: f6a8ad13...        # from the jobs' LAVA results, filled by round report
kernel: v6.12.117-rt23       # kernel_describe of the submission
boards: [bbb, c2d, rpi3-32, rpi3-64]
submissions:                 # what round start ran, from config.yml "rounds"
  - {}
  - {flavors: [rt], testsuites: stress-ng-class}
jobs:                        # every job submitted, with what it is
  966: {board: bbb, flavor: rt, test: rt-tests}
  ...
reruns:                      # old job: the job that replaces it
  961: 1020
reported: 2026-11-13T18:02:00Z   # round report fetched everything
exported: 2026-11-13T18:05:00Z   # round export sent it
```

Board, flavor and test per job come from the job's `srt.*` metadata
(`metrics.job_metadata`), so they also exist for backfilled rounds.

### Writing

- Only the `round` commands write the archive.
- Every file is written to `<name>.tmp` in the same directory and
  renamed: an interrupted run never leaves half a file.
- `round.yaml` is rewritten whole (tmp + rename) by `round start`,
  `rerun`, `report` and `export`; nothing else changes it.
- Secrets: before anything is written, every occurrence of the job's
  Artifactorial token is replaced by `<ARTIFACTORIAL_TOKEN>` in all of
  the job's files (definition, tests, suites, log). The token is the
  `ARTIFACTORIAL_TOKEN` parameter in the job's own definition; replace
  its literal value everywhere, it shows up in the log's command lines
  too. A test checks that no file of a saved job contains it.

### Dropping

`round drop N` removes `<archive>/N`. With `--metrics` it also deletes
the round's series in VictoriaMetrics (`/api/v1/admin/tsdb/delete_series`
with `{round="N"}`), after asking.

## The job database

`database.py`, SQLite at `system_config["database-path"]` (default
`~/.cache/srt-build/jobs.db`). Today:

- `test_suites`: one row per `lava` command and board (`suite_id` is the
  first job id, `machine`, `created_at`, `metadata` unused);
- `jobs`: every job id of that command (`helpers.py` calls
  `save_job_ids_to_db` with all of them, though `lava` prints only the
  first);
- `exported`: job ids `jobs export` has sent, with the sample count.

Its weak spots: it lives per checkout (jobs submitted from nitrogen are
missing elsewhere), it knows submissions, not rounds, so `jobs report`
without `--ids` takes only each board's last command, and it doesn't
know reruns.

Extended for rounds, not replaced:

- A table `rounds`: `number` (primary key), `lava` (instance), `started`,
  `srt_build`, `kernel`, `reported`, `exported`.
- `test_suites.round`: the round a submission belongs to (NULL for
  `lava` commands outside a round); a submission row per board and
  entry of `submissions`.
- A table `reruns`: `round`, `job_id`, `new_job_id`.
- `exported` stays as it is; `round export` marks its jobs there too,
  so `jobs export` doesn't send them twice.
- Migrations: `init_database` adds missing tables and columns
  (`ALTER TABLE ... ADD COLUMN`) and records a `user_version`
  (`PRAGMA user_version`), so older databases keep working.
- The default location moves next to the archive
  (`<archive>/jobs.db`) so rounds, their bookkeeping and their files are
  in one place; an existing `~/.cache/srt-build/jobs.db` is moved there
  once (or `database-path` keeps pointing to it). Run rounds from one
  host (nitrogen), or put the archive where every host sees it.
- `round reindex` rebuilds the round tables from the archive's
  `round.yaml` files (the fetched state from the `complete` markers);
  `exported` it can't know and leaves alone.

Who holds what: `round.yaml` the facts of a round (versions, jobs,
reruns), the database the index and what has happened since (fetched,
exported). Where both have it (jobs, reruns), `round` commands write
both, `round.yaml` first.

## Rounds

### Numbers and identity

- The next round number is the highest number in the archive plus one,
  or `--round N` (which must not exist yet). Not from LAVA: a reset LAVA
  starts its job ids at 1 again.
- A job is known by round and job id. `round.yaml` names the LAVA
  instance (`system_config["lava-instance"]`, default the LAVA host
  name), so job 912 of two LAVA instances can be told apart.
- Every job of a round carries `srt.round: "13"` in its metadata. In
  `jobs/job-base.jinja2`, next to `srt.build`, only when the context has
  a round (`{% if round is defined %}`: the environment is StrictUndefined).
  The archive stays the master; the tag lets LAVA's own UI and
  `jobs` commands see which round a job belongs to.

### What a round is: config.yml

```yaml
rounds:
  boards: [bbb, c2d, rpi3-32, rpi3-64]
  submissions:          # one lava submission per entry and board
    - {}                                          # = lava <board> --skip-build
    - {flavors: [rt], testsuites: stress-ng-class}
```

This replaces the two commands per board, and the `--testsuites default
stress-ng-class` trap (the default round is the suite `smoke`).

### Commands

`srt-build round ...`, a new command group next to `jobs` (main.py,
commands/cmd_round*.py).

- `round start [--boards ...] [--round N] [--dry-run]`
  - Before submitting: print srt-build version, kernel, boards; warn and
    ask when the srt-build checkout is dirty or behind its upstream
    (`git status -sb` / `git rev-list @{u}..HEAD` and `HEAD..@{u}` after
    a fetch), and when the LAVA server's free disk is below a limit
    (`ssh` like contrib scripts, or skip if not reachable).
  - Writes `round.yaml` (without jobs) before the first submission.
  - Runs the submissions of config.yml per board through the same code
    as `cmd_lava` (`--skip-build`), with `round` in the job context.
    The job ids come from where `helpers.py` already saves them
    (`save_job_ids_to_db`, now with the round); `cmd_lava` returning
    them is the cleaner way if that code allows.
  - Adds every job to `round.yaml` and the database as it is submitted,
    prints the round whole at the end: number, versions, one line per
    job.
- `round status [N]` (default: the newest round): per job state and
  health from LAVA, the rerun mapping, free disk on the LAVA server.
- `round wait [N]`: block until every job (after reruns) is Finished;
  one line per job that finishes not Complete, as it happens. Replaces
  the round-watch and disk-watch scripts used for rounds 12 and 13.
- `round rerun N JOB`: resubmit JOB's definition unchanged (it carries
  `srt.round`) through XML-RPC (`lava_api.rpc_from_lavacli`), record
  `reruns: {JOB: NEW}` in round.yaml. For lab failures; the replaced job
  stays in the archive but counts nowhere.
- `round report [N]`: fetch every finished job that has no `complete`
  into the archive (job, tests, suites, log, uploads; scrubbed), fill
  `test_definitions.commit`, write `report.txt`, print the report.
  Reads from the archive: `report.summarize_job` takes the archived
  files exactly as it takes LAVA's answers today. Exit 1 on problems,
  like `jobs report`.
- `round compare A B`: line up board, flavor, test and workload of two
  rounds (max latency, problems), from the archive.
- `round export [N | --all] [--dry-run] [--force]`: build the samples
  from the archive (`metrics.job_samples(job, tests, summary, uploads)`
  with everything read from files), add the label `round`, send them;
  set `exported` in round.yaml. Replaced jobs are left out. `--all`
  refills VictoriaMetrics from the whole archive.
- `round list`: the rounds in the archive, one line each (number, date,
  kernel, jobs, problems, reported/exported).
- `round drop N [--metrics]`: see above.
- `round import N --ids LIST` (backfill only): build a round from jobs
  that already ran; round.yaml from their metadata, then as `round
  report`.

### Reuse

- `report.summarize_job`, `report.format_report`, `metrics.job_samples`,
  `metrics.artifact_urls` work on plain data: feed them from the archive
  instead of `LavaApi`. A small `archive.py` (read and write a round, a
  job; scrubbing; atomic writes) with the same accessors as `LavaApi`
  (`job`, `tests`, `suites`, `log`) lets the rest stay as it is.
- `cmd_jobs_report.fetch_summaries` and `_save` are what `round report`
  does; `cmd_jobs_export.fetch_artifacts` fetches the uploads.
- `jobs report` and `jobs export` without `--ids` can then take the
  newest round from the database instead of each board's last command
  (the TODO item).
- `jobs report --save` stays for jobs outside rounds.

## VictoriaMetrics and the dashboards

- Samples of round jobs get the label `round` ("13"). The `job` label
  stays (the dashboards link to LAVA with it).
- A new label is a new series: before rounds 10-13 are exported from
  the archive with `round`, delete their old series in VictoriaMetrics
  (the user's call, see doc/TODO.md "Smaller").
- Dashboards (`grafana.py`, rendered by `jobs dashboard`): the overview's
  trends with the round on the x axis: instant queries over the range,
  format table, e.g.
  `max by (round, flavor) (max_over_time(srt_latency_us{<sel>, stat="max"}[$__range]))`,
  a "Convert field type" transform making `round` a number, Grafana's
  Trend panel (x: round, a line per flavor or workload); a bar chart for
  two rounds side by side. Check the Grafana version on monitor first
  (Trend panel: Grafana 10+). The time-based detail dashboard stays.

## Steps

Each step is useful on its own; tests with every step (`tests/`, ruff,
black; `pytest` must stay green).

1. **Archive and backfill.** `archive.py`, the database extension with
   its migration, `round import`, `round report`, `round list`, `round
   reindex`. Backfill while LAVA and Artifactorial still
   have the data (uploads expire after 90 days: rounds 10-13 from
   2026-11-12/13, so before 2027-02-10):
   - round 10: the jobs with `srt.build` 81767ac (doc/TUNING.md, "Round 10")
   - round 11: 730-753 (stress-ng classes only)
   - round 12: 912-965
   - round 13: 966-1019

   Done when: the four rounds are in the archive with uploads, no file
   contains the token, `round report 12` prints the same table as
   `~/lava-runs/r12/report.txt`, an old jobs.db (a copy of nitrogen's)
   migrates and `jobs report`/`jobs export` still work on it, and
   `round reindex` on an empty database gives the same round tables.
2. **Export from the archive.** `round export`, `round` label. Done when:
   `round export 12 --dry-run` gives the same 7006 samples as `jobs
   export --ids 912-965 --dry-run` apart from the `round` label (a test
   on a saved job proves it per sample).
3. **Rounds from the start.** config.yml `rounds`, `srt.round` in
   job-base, `cmd_lava` returning all ids, `round start`, `status`,
   `wait`, `rerun`, `compare`, `drop`. Done when: round 14 is started
   with `round start`, followed with `round wait`, reported and exported
   with the round commands only.
4. **Dashboards by round.** Delete the old series of rounds 10-13 (user),
   `round export --all`, Trend panels in `grafana.py`.

Rules that hold throughout (the lab's): no deploys or LAVA changes while
a round runs; the user pushes; never print the VictoriaMetrics password
or the Artifactorial token.
