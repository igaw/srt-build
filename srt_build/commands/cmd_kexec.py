"""Kexec command - install and kexec kernel on remote machine."""


def add_parser(subparser):
    """Add kexec command parser."""
    kpsg = subparser.add_parser('kexec')
    kpsg.add_argument('machine', help='Target machine')
    kpsg.add_argument('--append', default='')
    kpsg.add_argument('--rootfs', default='')
    kpsg.set_defaults(func=cmd_kexec)
    return kpsg


def cmd_kexec(ctx):
    """Install kernel and kexec on remote machine via SSH."""
    # Import necessary functions from main module when refactored
    # run_cmd, etc.
    pass
