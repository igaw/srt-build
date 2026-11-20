Introduction
============

srt-build is the test half of the stable PREEMPT_RT releases: stable-rt-tools
(``srt``) makes a release, srt-build builds it for the boards of the lab and
tests it there before it is published.

In the kernel tree, srt-build

- configures and builds a kernel per board and *flavor* (``rt``,
  ``rt-isolcpus``, ``nohz``, ``none``, ...: a kernel configuration, and
  the kernel arguments and tests to run with it),
- installs the kernels where LAVA's jobs boot them from,
- renders a LAVA job per test from the templates in ``jobs/`` and submits
  them.

Every submission belongs to a *round*: a release round is the reference
run of a kernel, every board and every test; a test round is anything
else. The round archive keeps what was submitted and the results, the
master copy LAVA, the dashboards and Artifactorial are filled from.

The goal of the lab: the same kernel gives the same results in every
round, so a change in the results means a change in the kernel.
`doc/TUNING.md <https://github.com/igaw/srt-build/blob/main/doc/TUNING.md>`_
describes how the boards are set up for that, what the results normally
look like and what was learned on the way.
