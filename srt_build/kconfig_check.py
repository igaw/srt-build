"""Checks of a merged kernel config, for `config --check`.

Two questions per board and flavor:

- Which preemption model, tick mode and SMP setting does the kernel
  end up with? Kconfig choices and dependencies can silently override
  a fragment (e.g. arm64 is always SMP; PREEMPT_LAZY needs
  ARCH_HAS_PREEMPT_LAZY).
- Which values requested by a fragment did not make it into the final
  .config? That finds symbols a kernel version renamed or removed
  (e.g. PREEMPT_RT_FULL) and dependencies that aren't met.
"""

import re

_LINE = re.compile(r"^(CONFIG_\w+)=(.*)$")
_UNSET = re.compile(r"^# (CONFIG_\w+) is not set$")
_MODELS = ("PREEMPT_NONE", "PREEMPT_VOLUNTARY", "PREEMPT", "PREEMPT_LAZY")


def parse_config(text):
    """{"CONFIG_X": value}; "# CONFIG_X is not set" gives "n"."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        m = _LINE.match(line)
        if m:
            values[m.group(1)] = m.group(2)
            continue
        m = _UNSET.match(line)
        if m:
            values[m.group(1)] = "n"
    return values


def requested_values(fragments):
    """What the fragments ask for: {symbol: (value, fragment name)}.

    fragments is a list of (name, text) in merge order; a later
    fragment overrides an earlier one, as merge_config.sh does.
    """
    wanted = {}
    for name, text in fragments:
        for sym, value in parse_config(text).items():
            wanted[sym] = (value, name)
    return wanted


def not_applied(wanted, final):
    """Requested values that the final config doesn't have.

    Returns a list of (symbol, requested, actual, fragment); a symbol
    missing from the final config counts as "n".
    """
    out = []
    for sym, (value, fragment) in sorted(wanted.items()):
        actual = final.get(sym, "n")
        if actual != value:
            out.append((sym, value, actual, fragment))
    return out


def preempt_summary(final):
    """The scheduling-relevant settings of a final config."""

    def on(sym):
        return final.get("CONFIG_" + sym) == "y"

    # PREEMPT is both a choice value and selected by PREEMPT_RT and
    # PREEMPT_LAZY; report the most specific one.
    models = [m for m in _MODELS if on(m)]
    model = models[-1] if models else "-"
    if on("PREEMPT_LAZIEST"):
        model = "PREEMPT_LAZIEST"
    if on("NO_HZ_FULL"):
        nohz = "full"
    elif on("NO_HZ_IDLE"):
        nohz = "idle"
    elif on("HZ_PERIODIC"):
        nohz = "periodic"
    else:
        nohz = "-"
    return {
        "model": model,
        "rt": on("PREEMPT_RT"),
        "dynamic": on("PREEMPT_DYNAMIC"),
        "smp": on("SMP"),
        "nohz": nohz,
        "hz": final.get("CONFIG_HZ", "-"),
    }
