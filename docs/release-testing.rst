Testing a release
=================

A stable PREEMPT_RT release is tested after stable-rt-tools made it and
before it is published: after ``srt quilt release`` (the tags are local,
nothing is pushed) and before ``srt create``, see `Test the release
<https://stable-rt-tools.readthedocs.io/en/latest/quilt-workflow.html#test-the-release>`_
in the stable-rt-tools documentation. The release tree, e.g.
``~/rt/v6.12-rt`` at ``v6.12.118-rt24``, is the kernel tree for every
command below.

The test is a release round: every board, every flavor, the smoke tests
and the stress tests, with the release's kernels. ``round start`` builds
and installs them and submits the round, in one go.

1. Build and submit the release round
-------------------------------------

.. code-block:: console

  $ cd ~/rt/v6.12-rt
  $ srt-build round start --dry-run
  $ srt-build round start

``round start`` builds every flavor the round uses on each board of
``rounds: boards`` in ``config.yml``, each once, and installs the kernels
where the boards' jobs boot them from, all before the first job is
submitted: a build that fails stops ``round start`` with nothing submitted
and no round in the archive. Then it submits, per board, one ``lava
--skip-build`` per entry of ``rounds: submissions`` (the smoke tests of
every flavor, the stress-ng classes of ``rt``). The round gets the next
number (``13``) and records the kernel (``git describe``, e.g.
``v6.12.118-rt24``), the srt-build commit and every job; ``round list``
shows the kernel. ``--notes`` is only for what the kernel doesn't tell,
e.g. ``--notes "bbb on a new power supply"``. The builds take a while:
run it in a ``tmux`` or ``screen`` session.

``--skip-build`` submits with the kernels installed already, e.g. to
submit a round again on the same kernels.

The dry run builds nothing and submits nothing; it renders the jobs and
shows the warnings. ``round start`` warns, and asks, when the srt-build
checkout has local changes or isn't in sync with its upstream (a round
should be reproducible from a pushed commit), or when the LAVA server is
low on disk; it asks before the builds, so the answer isn't needed hours
later. It checks that ``lavacli`` runs before it builds.

2. Optional: a quick check per board first
------------------------------------------

.. code-block:: console

  $ srt-build lava bbb

``srt-build lava <board>`` builds and installs every flavor of one board
and submits only its smoke tests, as a test round of its own (``t4``,
...). A kernel which doesn't build or boot shows up here, before the
release round takes the lab for hours; ``srt-build round wait t4``,
``srt-build round report t4``. After it, ``round start --skip-build``
uses those kernels.

3. Follow and report
--------------------

.. code-block:: console

  $ srt-build round wait               # until every job finished
  $ srt-build round report             # fetch into the archive, the table

``round wait`` prints every job which finishes not Complete, as it does,
and shows the round's progress: finished, running and queued jobs, the
time so far and about how long is left (from the same jobs in earlier
rounds).
A lab failure (the board didn't power on, the network dropped): submit the
job again with ``srt-build round rerun 13 <job>``; the new job replaces it.

``round report`` fetches the finished jobs into the round archive and
prints a table of all jobs; it exits with 1 if a job has a problem: not
Complete, a failed test case or upload, a test which reported no results,
a kernel warning, BUG, Oops, panic, RCU stall or hung task on the console,
or a max latency above 1 ms. "retried" (bbb's boot retry) is not a
problem.

4. Compare with the last release
--------------------------------

.. code-block:: console

  $ srt-build round list               # the rounds, with their kernel
  $ srt-build round compare            # the new round against the one before
  $ srt-build round compare 12 13      # or any two: rt23's round against rt24's

``round compare`` lines up the max latency per board, flavor, test and
workload of both rounds, with the change, what only one of them has,
and the jobs with problems of either. Without rounds it takes the newest
release round and the release round before it. It judges as `doc/TUNING.md
<https://github.com/igaw/srt-build/blob/main/doc/TUNING.md>`_ says: the
median changes 5-9 % from round to round, one test in ten up to 30-40 %,
and small values (c2d) swing more in percent, so only a change of at
least 40 % and 20 us is marked "regression" (``compare-min-percent``,
``compare-min-us`` in the configuration). Only a longer latency counts:
a shorter one is never a regression, however large the change (the
patched rtla took a stress-ng column from 20 ms to 0.2 ms). For a regression rerun the
job, and if it stays, see :doc:`debugging`. ``--check`` exits with 1 on
a regression or a job of the new round not Complete; a problem ``round
report`` flags in both rounds alike (a max latency above 1 ms on the
Pis) doesn't fail it.

5. Export
---------

.. code-block:: console

  $ srt-build round export             # to VictoriaMetrics, the dashboards

6. Back to the release
----------------------

The release passed: go on with ``srt create``, ``srt sign``, ``srt
check``, ``srt upload``, ``srt push`` and ``srt announce``.

A problem in the kernel: ``srt quilt undo`` takes the release back as long
as nothing is pushed; fix the patch queue, redo the release from ``srt
quilt refresh`` and test again.

With srt test
-------------

stable-rt-tools runs the test itself: ``srt test`` runs ``TEST_COMMAND``
of its ``srt.conf`` with ``sh -c`` in the worktree of the series, and
its exit code is the test's result. For srt-build, in the group of the
series (or ``[DEFAULT]`` for all series), with srt-build in a checkout
of its own at ``~/rt/srt-build`` (``srt-build`` alone if it is on
``PATH``):

.. code-block:: ini

   [linux/stable-rt/v6.12-rt]
   PRJ_DIR = /pub/linux/kernel/projects/rt/6.12
   WORKFLOW = quilt
   TEST_COMMAND =
       cd {worktree}
       $HOME/rt/srt-build/srt-build round start --notes "{tag}" --yes
       $HOME/rt/srt-build/srt-build round wait --report
       $HOME/rt/srt-build/srt-build round compare --check --result "$SRT_TEST_RESULT"

``{worktree}`` and ``{tag}`` are srt's placeholders, ``$HOME`` and
``$SRT_TEST_RESULT`` are left to ``sh``. ``srt test --dry-run`` in the
worktree of the series shows the lines for the release and runs
nothing.

``round start --yes`` builds, installs and submits the release round
without asking (``--notes`` with the release, ``{tag}``, e.g.
``v6.12.119-rt25``). ``round wait --report`` waits for the round started
last and fetches it into the archive; ``round compare --check`` compares
it with the release round before and decides. sh runs the lines without
``set -e``: a line that fails doesn't stop the next, and the exit code is
the last line's, the compare's. So ``round wait --report`` exiting 1 for
the known flags (a max latency above 1 ms) doesn't fail the test, only a
regression or a job not Complete does. ``srt test`` waits as long as the
round runs, hours: run it in ``tmux`` or ``screen``. Meanwhile it shows
``round wait``'s progress line (``srt test`` leaves the terminal to the
command), e.g. ``round 20: 31/54 finished, 2 running, 21 queued, 3h12m
so far, about 2h40m left``. To only submit, keep
the ``round start`` line alone and run the other two later yourself.

While ``round start`` builds, ``srt test`` shows where it is: the plan
(``building 14 kernels: ...``), per kernel ``build 3/14: rpi3-64 nohz
(last time 6m12s)`` and ``built rpi3-64 nohz in 5m58s (3 of 14 done,
about 40m left)``, from the durations of the last builds; then the
submissions and how long ``round start`` took.

``srt test`` passes a file in ``$SRT_TEST_RESULT``; ``--result`` writes
the compare's result there as JSON: ``status`` (``pass`` or ``fail``), a
one-line ``summary`` ("round 20 (v6.12.119-rt25) against 19: 54 jobs, no
regressions", or the regressions named), the two rounds, the regressions
and, with ``grafana-url`` in srt-build's configuration, the ``url`` of
the "RT rounds compared" dashboard of both: ``system_config:
grafana-url: http://monitor.lan:3000`` in ``config.yml`` (srt-build
reads the first ``config.yml`` it finds, its checkout's before
``~/.config/srt-build/config.yml``). srt shows the summary and the
link in ``srt status`` and keeps them in its log (``srt log``). Without
``SRT_TEST_RESULT`` (the command run by hand) the argument is empty and
nothing is written.

With an agent
-------------

With ``srt mcp`` (stable-rt-tools) and ``srt-build mcp``, an agent can make
the release and test it in one session: ``lava`` and ``round_start`` run as
tasks, ``round_status``, ``round_report`` and ``round_compare`` give the
results as data. Building and submitting needs a server started with
``--allow-submit``; see :doc:`agents`.
