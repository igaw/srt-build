Debugging on a board
====================

An outlier or a failed job: look at what the job already has first, its
log, its test cases and its uploads (above all rtla's noise histograms),
and at the same test in earlier rounds and on other boards. Rerun it a
few times. If that doesn't settle it, trace it on the board.

.. code-block:: console

  $ srt-build jobs hack 67 --minutes 90   # boot like job 67, keep it up
  $ ssh root@<address>                    # printed once the board is up

``jobs hack`` takes the deploy and boot actions of an existing LAVA job
(same board, kernel, dtb and rootfs; ``--kernel URL`` swaps the kernel)
and replaces its tests with one which installs your SSH key (``--key``,
default ``~/.ssh/id_ed25519.pub``), starts sshd, prints the board's address
and waits. ``touch /tmp/hack-done`` on the board ends the session early.

The tests run about 30 s after boot, and some effects only show then.
``--file`` copies local scripts to ``/root`` and ``--run CMD`` starts one
right after boot; its output lands in the job log:

.. code-block:: console

  $ srt-build jobs hack 67 --minutes 10 --file trace-run.sh \
        --run "./trace-run.sh sv svsematest -q -t -a -p 98 -D 1m -b 1000"

``contrib/hack/`` has the scripts which found the lab's latency problems;
each says how to run it. They stop at a threshold and keep the trace.
Copy the traces off the board before the session ends: its root file
system is gone with it.

Hack sessions are no rounds: they never go into the archive or the
dashboards; ``jobs purge`` deletes what they leave in LAVA.
