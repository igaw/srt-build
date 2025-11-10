"""Commands package for srt-build."""

# Import all command modules so they're available when commands package is imported
from . import (
    cmd_config,
    cmd_build,
    cmd_install,
    cmd_lava,
    cmd_smoke,
    cmd_jobs,
    cmd_jobs_list,
    cmd_jobs_results,
    cmd_jobs_compare,
    cmd_jobs_cancel,
    cmd_kexec,
    cmd_all,
)

__all__ = [
    'cmd_config',
    'cmd_build',
    'cmd_install',
    'cmd_lava',
    'cmd_smoke',
    'cmd_jobs',
    'cmd_jobs_list',
    'cmd_jobs_results',
    'cmd_jobs_compare',
    'cmd_jobs_cancel',
    'cmd_kexec',
    'cmd_all',
]
