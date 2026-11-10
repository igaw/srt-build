"""kconfig_check: what fragments ask for vs. what the final .config has."""

from srt_build.kconfig_check import (
    not_applied,
    parse_config,
    preempt_summary,
    requested_values,
)


def test_parse_config():
    text = (
        "# comment\n"
        "CONFIG_SMP=y\n"
        '# CONFIG_EMBEDDED is not set\nCONFIG_HZ=250\nCONFIG_LOCALVERSION="-rt"\n \n'
    )
    assert parse_config(text) == {
        "CONFIG_SMP": "y",
        "CONFIG_EMBEDDED": "n",
        "CONFIG_HZ": "250",
        "CONFIG_LOCALVERSION": '"-rt"',
    }


def test_later_fragment_wins():
    wanted = requested_values(
        [
            ("base", "CONFIG_SMP=y\nCONFIG_HZ=1000\n"),
            ("up", "# CONFIG_SMP is not set\n"),
        ]
    )
    assert wanted == {"CONFIG_SMP": ("n", "up"), "CONFIG_HZ": ("1000", "base")}


def test_not_applied_finds_removed_and_overridden_symbols():
    wanted = requested_values(
        [
            (
                "rt",
                "CONFIG_PREEMPT_RT_FULL=y\n# CONFIG_GONE is not set\n"
                "# CONFIG_CPU_IDLE is not set\nCONFIG_SMP=y\n",
            )
        ]
    )
    final = parse_config("CONFIG_CPU_IDLE=y\nCONFIG_SMP=y\n")
    assert not_applied(wanted, final) == [
        ("CONFIG_CPU_IDLE", "n", "y", "rt"),
        ("CONFIG_PREEMPT_RT_FULL", "y", "n", "rt"),
    ]


def test_preempt_summary_rt():
    final = parse_config(
        "CONFIG_PREEMPT=y\nCONFIG_PREEMPT_RT=y\nCONFIG_PREEMPT_DYNAMIC=y\n"
        "CONFIG_SMP=y\nCONFIG_HZ_PERIODIC=y\nCONFIG_HZ=250\n"
    )
    assert preempt_summary(final) == {
        "model": "PREEMPT",
        "rt": True,
        "dynamic": True,
        "smp": True,
        "nohz": "periodic",
        "hz": "250",
    }


def test_preempt_summary_lazy_and_nohz_full():
    final = parse_config(
        "CONFIG_PREEMPT_LAZY=y\nCONFIG_PREEMPT=y\nCONFIG_NO_HZ_FULL=y\n"
        "CONFIG_NO_HZ_IDLE=y\n"
    )
    p = preempt_summary(final)
    assert (p["model"], p["nohz"], p["smp"]) == ("PREEMPT_LAZY", "full", False)
