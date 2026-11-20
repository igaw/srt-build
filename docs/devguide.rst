Developer Guide
===============

.. code-block:: console

  $ python -m venv .venv && . .venv/bin/activate
  $ pip install -r requirements-dev.txt
  $ black . && ruff check .
  $ pytest -q
  $ pip install -r docs/requirements.txt && make -C docs html

CI runs ruff, black and pytest for every push and pull request.

No test talks to the lab: LAVA, Artifactorial and VictoriaMetrics are real
servers whose data a test must never change. ``tests/conftest.py`` fails
every network access a test doesn't fake; ``tests/lava_fake.py`` is a
LAVA for the round commands.

Keep changes small, with tests for the new behaviour
(``tests/test_job_templates.py`` renders every template for every board
and flavor). A change of a board's setup goes with an update of
``doc/TUNING.md``: what, why, the evidence (LAVA job numbers), and what
didn't help.

The repository is public: no lab host names, addresses, tokens or
passwords. LAVA is found through the lavacli identity, VictoriaMetrics
through ``~/.config/srt-build/metrics.yml``.
