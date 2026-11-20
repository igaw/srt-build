Agents
======

``srt-build mcp`` serves the lab to an agent, e.g. Claude Code, as an
`MCP <https://modelcontextprotocol.io>`_ server on stdin and stdout, the
same way as ``srt mcp`` of stable-rt-tools. The kernel trees are named
relative to ``--trees``:

.. code-block:: console

  $ claude mcp add srt-build -- ~/srt-build/srt-build mcp --trees ~/rt

Its tools run srt-build itself, without a terminal:

``boards``, ``tests``, ``rounds``, ``round_status``, ``round_compare``
    Read the configuration, the archive and LAVA.
``round_report``, ``round_export``
    Fetch and report a round, send it to VictoriaMetrics, as by hand.
``lava``, ``round_start``
    Build, install and submit a test round; build, install and submit a
    release round (``skip_build``: with the installed kernels; a dry run
    unless asked otherwise). They run as
    tasks in their own session, which outlive the client, one per tree.
``task_status``, ``tasks``
    Follow the tasks: running, finished with exit code, or lost, and the
    end of the log (``~/.local/state/srt-build/mcp``).
``round_rerun``, ``round_drop``
    Replace a job of a round; remove a round (a dry run unless asked
    otherwise).

Whoever starts the server decides what the agent may do to the lab:
``lava``, a real ``round_start`` and ``round_rerun`` take the boards and
need ``--allow-submit``; a real ``round_drop`` needs ``--allow-delete``.
Without them the agent is told to ask.

The repository has a Claude Code skill, ``.claude/skills/rt-lab``, for
running and judging rounds.
