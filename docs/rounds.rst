Rounds
======

A round is the unit which is submitted, followed, reported and exported.
Its results go to the round archive (``~/.local/share/srt-build/rounds``,
``round-archive`` in ``system_config``), the master copy and the only
record of what was submitted. `doc/ROUNDS.md
<https://github.com/igaw/srt-build/blob/main/doc/ROUNDS.md>`_ describes the
design.

Release rounds and test rounds
------------------------------

Release rounds (``10``, ``11``, ...) are the reference runs:
``round start`` submits, per board, one ``lava --skip-build`` per entry of
``rounds: submissions`` in ``config.yml``. Everything else is a test round
(``t1``, ``t2``, ...): each ``lava`` or ``smoke`` command makes one, and
``round start --test`` does too. ``round prune`` drops test rounds after
``test-retention-days``.

Without a round id the commands take the round started last. Every job
carries ``srt.round`` in its metadata.

.. code-block:: console

  $ srt-build round start --dry-run     # what it would submit
  $ srt-build round start               # release round, the next number
  $ srt-build round start --build       # build and install the kernels first
  $ srt-build round start --test --notes "nohz=off"   # a test round
  $ srt-build round status              # every job's state, LAVA's free disk
  $ srt-build round wait                # until all have finished
  $ srt-build round rerun 13 961        # a lab failure: run the job again
  $ srt-build round report              # fetch into the archive, the table
  $ srt-build round export              # to VictoriaMetrics, label round
  $ srt-build round compare 12 13       # max latency side by side
  $ srt-build round list                # the rounds in the archive

``round list``, ``round status``, ``round compare`` and ``round report``
print JSON with ``--json``.

Running jobs by hand
--------------------

.. code-block:: console

  $ srt-build lava bbb                  # build, install, submit all flavors
  $ srt-build lava bbb --skip-build     # the installed kernels
  $ srt-build lava bbb --split          # one job (boot) per test
  $ srt-build lava bbb --testsuites stress-ng-class   # the stress classes
  $ srt-build lava bbb --flavors rt --tests cyclictest

A flavor with a ``combined`` list in ``config.yml`` (``rt``,
``rt-isolcpus``) runs those tests in one job, one boot; each test stays a
LAVA test suite of its own, reported and exported as if it had its own
job. ``--split``, ``--tests`` and other test suites give one job per
test, for chasing a strange result.

Reports
-------

``round report`` fetches every finished job the archive doesn't have yet
(job, results, log, uploads, with the Artifactorial token replaced),
writes ``report.txt`` and prints the table: health, maximum latency,
uploads and problems per job. Run it again for the jobs which weren't
finished. Then it deletes the archived uploads from Artifactorial
(``--keep-uploads``: not).

A job counts as a problem when LAVA reports it Incomplete, but also when it
is Complete and still broken: a failed test case or LAVA action, a failed
upload, a test definition which reported no results, a kernel warning,
BUG, Oops, panic, RCU stall, hung task or test-script error on the
console, or a max latency above 1 ms. A boot LAVA had to retry (bbb) is
"retried", not a problem.

``jobs watch`` and ``jobs report`` do the same for LAVA jobs outside a
round, e.g. ``srt-build jobs report bbb --ids 13-27``.

Rounds which ran before ``round start`` existed:

.. code-block:: console

  $ srt-build round import 12 --ids 912-965 --keep-uploads

Dashboards
----------

``round export`` turns each finished job into VictoriaMetrics samples at
the job's end time: whether it had problems, min/avg/max latency per
thread, and the histograms of the rt-tests/rtla JSON uploads. ``jobs
dashboard DIR --lava-url URL`` writes the Grafana dashboards.

Removing data
-------------

Always after listing it and asking:

.. code-block:: console

  $ srt-build round drop t2 --metrics   # archive, uploads, series
  $ srt-build round prune --dry-run     # test rounds past test-retention-days
  $ srt-build jobs purge --ids 755-777 --metrics   # hack sessions
