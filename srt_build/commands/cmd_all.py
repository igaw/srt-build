"""All command - run config, build, and kexec in sequence."""
from .cmd_config import cmd_config
from .cmd_build import cmd_build
from .cmd_kexec import cmd_kexec


def add_parser(subparser):
    """Add all command parser."""
    apsg = subparser.add_parser('all')
    apsg.add_argument('machine', help='Target machine')
    apsg.add_argument('--config')
    apsg.add_argument('--config-base', default='')
    apsg.add_argument('--append', default='')
    apsg.add_argument('--flavor', default='')
    apsg.add_argument('--rootfs', default='')
    apsg.set_defaults(func=cmd_all)
    return apsg


def cmd_all(ctx, kernel_config):
    """Run config, build, and kexec commands in sequence."""
    cmd_config(ctx, kernel_config)
    c = cmd_build(ctx)
    if c:
        return
    cmd_kexec(ctx)
