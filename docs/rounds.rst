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
``round start`` builds and installs every board's kernels (``--skip-build``:
the installed ones), then submits, per board, one ``lava --skip-build``
per entry of
``rounds: submissions`` in ``config.yml``. Everything else is a test round
(``t1``, ``t2``, ...): each ``lava`` or ``smoke`` command makes one, and
``round start --test`` does too. ``round prune`` drops test rounds after
``test-retention-days``.

Without a round id the commands take the round started last. Every job
carries ``srt.round`` in its metadata.

.. code-block:: console

  $ srt-build round start --dry-run     # what it would submit
  $ srt-build round start               # build, install, release round
  $ srt-build round start --skip-build  # with the kernels installed already
  $ srt-build round start --test --notes "nohz=off"   # a test round
  $ srt-build round status              # every job's state, LAVA's free disk
  $ srt-build round wait                # until all have finished
  $ srt-build round rerun 13 961        # a lab failure: run the job again
  $ srt-build round repeat 15           # its jobs again, a new round (no tree)
  $ srt-build round repeat 15 --count 5 # five rounds in one go, a batch
  $ srt-build round repeat 15 --tests stress-ng-io --boards rpi3-64
                                        # only those of its jobs
  $ srt-build round wait --batch 16 --report   # each round, reported when done
  $ srt-build round cancel --batch 16   # give the lab back: the jobs not finished
  $ srt-build round report              # fetch into the archive, the table
  $ srt-build round export              # to VictoriaMetrics (round report does it)
  $ srt-build round compare 12 13       # max latency side by side
  $ srt-build round compare --check     # newest release round against the one
                                        # before: exit 1 on a regression
  $ srt-build round list                # the rounds in the archive

``round list``, ``round status``, ``round compare`` and ``round report``
print JSON with ``--json``.

Batches of rounds
-----------------

``--count K`` (``round start`` and ``round repeat``) submits K rounds
at once, the next K numbers, each a round of its own with ``batch:
<first>`` in ``round.yaml``. LAVA runs a board's jobs by priority, then
in the order submitted, so the rounds run back to back with nobody
watching. Their jobs are priority ``low`` (``--priority``: ``low``,
``medium``, ``high`` or 0-100), so other people's jobs go first. The
disk check wants ``lava-disk-min-gb`` and ``lava-round-gb`` (1 GB) for
each round after the first.

``round wait`` shows where the round is: finished, running and queued
jobs, the time so far and about how long is left, from how long the
same jobs took in earlier rounds (on a terminal in one line, updated in
place; ``--quiet`` turns it off)::

  round 20: 31/54 finished (1 not Complete), 2 running, 21 queued, 3h12m so far, about 2h40m left

``round wait --batch 16`` follows the batch round by round, with the
batch's totals;
``--report`` reports each round as soon as it has finished, while the
later ones are still queued. A rerun of a job lands behind the rounds
still queued; it counts in its own round as always. ``round cancel``
cancels the jobs not finished; the rounds stay in the archive.

Back to back measures one stretch of time; rounds spread over days
also show what changes between them. Say which in ``--notes``.

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
finished. Then it deletes the archived uploads from Artifactorial and,
once every job is in, sends the round to VictoriaMetrics as ``round
export`` does, once. ``--no-export`` skips the export; ``--keep-uploads``
skips both, for a second archive next to the one that exports. If
VictoriaMetrics can't be reached, ``round report`` only warns and
``round export N`` sends the round later.

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
dashboard DIR --lava-url URL`` writes the Grafana dashboards. What they show, and how the normal range (the green band) is computed:
:doc:`dashboards`.

Removing data
-------------

Always after listing it and asking:

.. code-block:: console

  $ srt-build round drop t2 --metrics   # archive, uploads, series
  $ srt-build round prune --dry-run     # test rounds past test-retention-days
  $ srt-build jobs purge --ids 755-777 --metrics   # hack sessions
