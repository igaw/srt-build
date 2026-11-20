User Guide
==========

Installation
------------

srt-build runs from its checkout, with the system's ``python3`` (3.12 or
newer) and its Jinja2 and PyYAML, e.g. the distribution's packages
(``python3-jinja2`` and ``python3-pyyaml``, or ``python-jinja`` and
``python-yaml``):

.. code-block:: console

  $ git clone https://github.com/igaw/srt-build.git ~/srt-build
  $ ln -s ~/srt-build/srt-build ~/.local/bin/srt-build

Run it as ``srt-build`` in the kernel tree of the release to test.

Prerequisites
-------------

- A LAVA server with the boards, and a lavacli identity for it in
  ``~/.config/lavacli.yaml`` (identity ``default``): srt-build finds LAVA's
  REST and XML-RPC API through it. lavacli itself needn't be installed.
- The cross compilers of the boards (``CROSS_COMPILE`` in ``config.yml``,
  e.g. ``arm-linux-gnu-``) and what a kernel build needs.
- ssh access to where the boards boot their kernels from (the ``install``
  commands of the boards in ``config.yml``) and to the LAVA server, whose
  free disk srt-build checks before a round.
- An Artifactorial instance for the result files the tests upload, its
  token as ``artifactorial_token`` in a board file or
  ``artifactorial-token`` in ``system_config``.
- For the dashboards: VictoriaMetrics behind vmauth, configured in
  ``~/.config/srt-build/metrics.yml`` (``url``, ``username``,
  ``password``).

Configuration
-------------

srt-build reads the first ``config.yml`` it finds: the one of the
checkout, then the current directory's, then
``~/.config/srt-build/config.yml``. It describes

``kernel_config``
    the configuration fragments (``configs/``) of each flavor;
``flavors``
    flavors which boot another flavor's kernel or add kernel arguments
    (``rt-isolcpus`` boots the ``rt`` kernel with isolated CPUs), and the
    tests a flavor runs in one boot (``combined``);
``machine_config``
    the boards: architecture, defconfig, image, command line, how to
    install the kernel, the flavors a board can't build;
``rounds``
    what a release round submits: the boards and a ``lava`` command per
    entry of ``submissions``, and how long test rounds are kept;
``system_config``
    local settings: the round archive (``round-archive``, default
    ``~/.local/share/srt-build/rounds``), the build directories, and
    ``lava-identity``, ``lava-api``, ``lava-ssh``, ``metrics-config`` to
    override where LAVA and VictoriaMetrics are found.

The repository is public: lab host names, addresses, tokens and
passwords stay in ``~/.config``, never in the checkout.

Checking kernel configs
-----------------------

.. code-block:: console

  $ srt-build config c2d --check

configures every flavor of the board in a scratch directory and shows
what it ends up as (preemption model, PREEMPT_RT, PREEMPT_DYNAMIC, SMP,
tick mode, HZ), plus every value a fragment requests that isn't in the
final config: renamed or removed symbols, and dependencies the
architecture doesn't meet.
