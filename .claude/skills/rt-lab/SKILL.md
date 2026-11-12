---
name: rt-lab
description: Run, check and debug PREEMPT_RT test rounds in the LAVA lab with srt-build. Use when submitting or watching a round, reading `jobs report`, comparing results with the reference, chasing a latency outlier or failed job on a board (reruns, `jobs hack` sessions with traces), or changing a board's kernel config, command line or test settings.
---

# PREEMPT_RT lab work with srt-build

The lab's goal: **the same kernel gives the same results in every round**,
so a change in the results means a change in the kernel. Judge every
change by that. `doc/TUNING.md` is the reference for how the boards are
set up, why, what the results normally look like (round 10 table,
normal variation) and what was learned; read it before changing a
setting or calling something a regression.

## A round

1. Submit (the user usually does this): `srt-build lava <board>` builds
   and submits; `--skip-build` reuses the installed kernels when only
   job templates, `config.yml` flavors or test-definitions changed, not
   `configs/`. rt and rt-isolcpus run their tests in one boot (one
   "combined" job, report rows per test); rerun single tests with
   `--flavors rt --tests <test>`, or everything a boot per test with
   `--split`.
2. Check the jobs carry what you expect before they run: the job
   definition's `metadata` (`srt.build`, `srt.kernel`) and its test
   definitions (e.g. `fair-server` only in rt rtla-osnoise on 6.12).
3. Watch: `srt-build jobs watch --since <last id before the round>
   --save <dir>`; it prints each job with a problem as it finishes. Run
   it in the background and report problems, not every job.
4. Report: `srt-build jobs report --ids <first>-<last> --save <dir>`.
   Problems are: not Complete, failed cases or uploads, definitions
   without results, kernel splats or script errors on the console, a
   max latency above 1 ms. "retried" (bbb boot) is not a problem.
5. Compare with the reference in `doc/TUNING.md` and with the previous
   round on the same kernel. Normal: median change 5-9 %, one test in
   ten up to 30-40 %; small values (c2d) swing more in percent. Only a
   change beyond both about 40 % and 20 us is worth a look.
6. Export (from the machine whose job database records what was sent):
   `srt-build jobs export --since 0` sends whatever is missing.

Stress rounds: `--testsuites stress-ng-class` (rtla timerlat next to
each stress-ng class; see "Stress tests" in `doc/TUNING.md` for the
excluded stressors). A stressor suspected of a result: run its class
per stressor with `contrib/hack/stress-ng-hunt.sh` in a hack session
(`FROM=<stressor>` resumes after a session ran out of time).

Don't change lab infrastructure (LAVA, mirrors) while a round runs.
One test per LAVA job; don't combine jobs.

## An outlier or a failed job

1. Look at what the job already has before running anything: its log
   (kernel messages, "RT throttling activated", "Fair server disabled",
   RCU stalls), its test cases, and its uploads, above all the rtla
   noise histograms (`osnoise_thread_noise_hist.txt`: which task or IRQ
   interrupted the measuring thread, how often, how long).
2. Same value on the same board in earlier rounds? Same on other
   boards? A stall at a fixed time after boot on all CPUs points at
   firmware (hwlat); a hit that only some runs of the same job get
   points at a timing interaction.
3. Rerun the job a few times with its definition from LAVA and a
   `job_name` like "rtla-osnoise (rerun 1 of 520)": the name keeps the
   reruns out of `jobs export`.
4. If reruns don't settle it, trace it in a `jobs hack` session (README,
   "Debugging on a board") with the scripts in `contrib/hack/`; they
   stop at a threshold and keep the trace. Thresholds depend on the
   board's noise floor: about 1 ms for bbb and the Pis, 200 us for c2d.
   Copy the traces off before the session ends; tell the user how long
   the boards are taken.
5. Explain the outlier from the trace (which task ran instead of the RT
   thread, and why), then fix the cause in the lab, not the numbers.

## Changing a setting

- Kernel config: a fragment in `configs/`, listed for the flavors in
  `config.yml` `kernel_config`; check with `srt-build config <board>
  --check` that it sticks. Needs a rebuild.
- Kernel command line: `config.yml` `flavors` (all boards) or a board's
  `kernel_args`; per test in its template (e.g. pi-stress's
  `rcutree.kthread_prio`).
- Settings at test time: `config.yml` `flavors` (e.g.
  `fair_server_off`, per kernel release and test) and
  `jobs/job-base.jinja2`. Every setting needs a check in the job that
  fails if it didn't take effect.
- Board quirks: `jobs/boards/<board>.yaml` (e.g. bbb's boot retry).
- Change the narrowest thing that fixes the problem: switching the fair
  server off for all tests fixed osnoise and broke pi-stress.
- Ask before changing an existing deliberate setting.

Then: tests (`pytest`), `black --check .`, `ruff check .`; add a test
for the new behaviour (`tests/test_job_templates.py` renders every
template for every board and flavor). Update `doc/TUNING.md` in the
same series: what, why, the evidence (LAVA job numbers), and what
didn't help.

## Keep out of this repository

It is public: no lab host names, addresses, tokens or passwords. LAVA
is found through the lavacli identity (`~/.config/lavacli.yaml`),
VictoriaMetrics through `~/.config/srt-build/metrics.yml`; pass public
URLs on the command line (`jobs dashboard --lava-url`).
